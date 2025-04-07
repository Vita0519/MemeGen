from loguru import logger
import tomllib
import os
import io
import re
import json
import random
import aiohttp
import asyncio
import time
from PIL import Image

from WechatAPI import WechatAPIClient
from utils.decorators import *
from utils.plugin_base import PluginBase
from meme_generator import get_meme


class MemeGen(PluginBase):
    """表情包生成器插件 - 基于微信群聊中的用户头像生成各种有趣的表情包"""
    description = "表情包生成器插件"
    author = "阿孟"
    version = "1.0.0"

    def __init__(self):
        super().__init__()
        
        # 获取配置文件路径
        config_path = os.path.join(os.path.dirname(__file__), "config.toml")
        
        try:
            with open(config_path, "rb") as f:
                config = tomllib.load(f)
                
            # 读取基本配置
            basic_config = config.get("basic", {})
            self.enable = basic_config.get("enable", True)
            
            # 读取缓存配置
            cache_config = config.get("cache", {})
            self.real_avatar_ttl = cache_config.get("real_avatar_ttl", 86400)  # 默认24小时
            self.default_avatar_ttl = cache_config.get("default_avatar_ttl", 43200)  # 默认12小时
            self.cleanup_interval = cache_config.get("cleanup_interval", 24)  # 默认24小时
            self.cleanup_threshold = cache_config.get("cleanup_threshold", 3)  # 默认3次
            self.cleanup_expire_days = cache_config.get("cleanup_expire_days", 7)  # 默认7天
            
            # 读取管理员配置
            admin_config = config.get("admin", {})
            self.local_admin_users = admin_config.get("admin_users", [])
            
            # 读取命令配置
            commands_config = config.get("commands", {})
            self.list_commands = commands_config.get("list_commands", ["表情列表"])
            
        except Exception as e:
            logger.error(f"加载MemeGen配置文件失败: {str(e)}")
            self.enable = False
            self.real_avatar_ttl = 86400
            self.default_avatar_ttl = 43200
            self.cleanup_interval = 24
            self.cleanup_threshold = 3
            self.cleanup_expire_days = 7
            self.local_admin_users = []
            self.list_commands = ["表情列表"]
            return
            
        # 创建临时文件夹
        self.temp_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "temp")
        os.makedirs(self.temp_dir, exist_ok=True)
        
        # 创建头像缓存目录
        self.avatar_dir = os.path.join(self.temp_dir, "avatars")
        os.makedirs(self.avatar_dir, exist_ok=True)
        
        # 加载表情配置
        self.meme_cache = {}  # 用于缓存meme生成器
        try:
            self.load_emoji_config()
        except Exception as e:
            logger.error(f"加载表情配置失败: {str(e)}")
            self.enable = False
            
    def load_emoji_config(self):
        """加载表情配置文件"""
        emoji_path = os.path.join(os.path.dirname(__file__), "emoji.json")
        if not os.path.exists(emoji_path):
            logger.error(f"表情配置文件不存在: {emoji_path}")
            raise FileNotFoundError(f"表情配置文件不存在: {emoji_path}")
            
        with open(emoji_path, "r", encoding="utf-8") as f:
            emoji_config = json.load(f)
        
        # 单人表情
        self.single_emojis = emoji_config.get("one_PicEwo", {})
        # 双人表情
        self.two_person_emojis = emoji_config.get("two_PicEwo", {})
        
        # 创建禁用表情追踪
        self.disabled_emojis = {}  # 格式: {group_id: set(disabled_meme_types)}
        self.globally_disabled_emojis = set()  # 全局禁用的表情类型
        
        logger.info(f"成功加载表情配置，单人表情: {len(self.single_emojis)}，双人表情: {len(self.two_person_emojis)}")

    @on_text_message()
    async def handle_text(self, bot: WechatAPIClient, message: dict):
        """处理文本消息"""
        if not self.enable:
            logger.info("MemeGen插件已禁用，忽略消息")
            return
            
        content = message.get("Content", "").strip()
        from_wxid = message.get("FromWxid", "")
        is_group = message.get("IsGroup", False)
        actual_user_id = message.get("ActualUserWxid", "")
        
        logger.info(f"MemeGen收到消息: {content}, 来自: {from_wxid}, 实际发送者: {actual_user_id}")
        
        # 检查是否请求表情列表
        if content in self.list_commands:
            await self.send_emoji_list(bot, from_wxid)
            return
            
        # 处理清理头像缓存命令
        if content.startswith("清理表情缓存") or content.startswith("清除表情缓存"):
            # 检查权限
            admin_users = self.get_admin_users()
            if actual_user_id not in admin_users:
                await bot.send_text_message(from_wxid, "只有管理员才能执行此操作！")
                return
                
            try:
                # 提取目标wxid，如果没有则清除所有
                parts = content.split(maxsplit=1)
                target_wxid = parts[1].strip() if len(parts) > 1 else None
                
                if target_wxid:
                    # 清除特定用户的头像缓存
                    files_removed = await self.clear_avatar_cache(target_wxid)
                    await bot.send_text_message(from_wxid, f"已清除用户 {target_wxid} 的头像缓存，移除了 {files_removed} 个文件")
                else:
                    # 清除所有低使用率的缓存
                    avatars_cleaned = await self.clear_all_avatar_cache()
                    await bot.send_text_message(from_wxid, f"已清除头像缓存，共移除了 {avatars_cleaned} 个文件")
                    
                return
            except Exception as e:
                logger.error(f"清理缓存出错: {str(e)}")
                await bot.send_text_message(from_wxid, f"清理缓存失败: {str(e)}")
                return
            
        # 检查是否是表情启用/禁用命令
        if re.match(r'^(全局)?(禁用|启用)表情\s+.+$', content):
            await self.handle_enable_disable_commands(bot, message)
            return
            
        # 提取@用户
        at_users = self.extract_at_users(content, message)
        
        # 输出at_users调试信息
        logger.info(f"提取到的@用户列表: {at_users}")
        
        # 如果没有@用户，则不处理（只处理@用户的情况）
        if not at_users:
            logger.info("未提取到@用户，不处理表情生成")
            return
            
        # 清理后的内容（移除@用户部分）
        clean_content = self.clean_at_text(content)
        logger.info(f"清理@后的内容: {clean_content}")
        
        # 检查表情是否被禁用
        group_id = from_wxid if is_group else None
        if (clean_content in self.globally_disabled_emojis or 
            (group_id in self.disabled_emojis and clean_content in self.disabled_emojis[group_id])):
            logger.info(f"表情 {clean_content} 已被禁用，不处理")
            return
        
        # 处理双人表情：格式为 "@用户A 触发词 @用户B"
        if len(at_users) >= 2:
            logger.info("检测到至少两个@用户，尝试生成双人表情")
            # 尝试查找双人表情触发词
            for trigger_word, emoji_type in self.two_person_emojis.items():
                if trigger_word in content:
                    logger.info(f"找到双人表情触发词: {trigger_word}, 类型: {emoji_type}")
                    # 获取第一个被@用户的头像
                    first_avatar = await self.download_avatar(bot, at_users[0], from_wxid if is_group else None)
                    if not first_avatar:
                        await bot.send_text_message(from_wxid, f"无法获取用户 {at_users[0]} 的头像")
                        return
                    
                    # 获取第二个被@用户的头像
                    second_avatar = await self.download_avatar(bot, at_users[1], from_wxid if is_group else None)
                    if not second_avatar:
                        await bot.send_text_message(from_wxid, f"无法获取用户 {at_users[1]} 的头像")
                        return
                    
                    # 生成并发送双人表情
                    await self.generate_and_send_meme(bot, from_wxid, emoji_type, [first_avatar, second_avatar], two_person=True)
                    logger.info(f"生成双人表情：{trigger_word}，使用用户 {at_users[0]} 和 {at_users[1]} 的头像")
                    return
            
            logger.info("未找到匹配的双人表情触发词")
                
        # 处理单人表情：格式为 "@用户 触发词"
        if len(at_users) == 1:
            logger.info("检测到一个@用户，尝试生成单人表情")
            # 检查消息中的所有单人表情触发词
            for trigger_word, emoji_type in self.single_emojis.items():
                if trigger_word in content:
                    logger.info(f"找到单人表情触发词: {trigger_word}, 类型: {emoji_type}")
                    # 获取被@用户的头像
                    avatar_path = await self.download_avatar(bot, at_users[0], from_wxid if is_group else None)
                    if avatar_path:
                        await self.generate_and_send_meme(bot, from_wxid, emoji_type, [avatar_path])
                        logger.info(f"生成单人表情：{trigger_word}，使用用户 {at_users[0]} 的头像")
                    else:
                        await bot.send_text_message(from_wxid, f"无法获取用户 {at_users[0]} 的头像")
                    return
            
            logger.info("未找到匹配的单人表情触发词")
        
        logger.info("消息处理完毕，没有找到匹配的表情生成条件")

    async def generate_and_send_meme(self, bot, to_wxid, emoji_type, avatars, two_person=False):
        """生成并发送表情包"""
        try:
            # 获取或创建meme生成器
            if emoji_type not in self.meme_cache:
                self.meme_cache[emoji_type] = get_meme(emoji_type)
            
            meme_gen = self.meme_cache[emoji_type]
            
            # 生成表情
            result = meme_gen(images=avatars, texts=[], args={"circle": True})
            
            # 处理协程结果
            if asyncio.iscoroutine(result):
                buf_gif = await result
            else:
                buf_gif = result
                
            # 发送表情
            await bot.send_image_message(to_wxid, buf_gif.getvalue())
            logger.info(f"成功发送表情: {emoji_type}")
            
        except Exception as e:
            logger.error(f"生成表情失败: {str(e)}")
            await bot.send_text_message(to_wxid, f"生成表情失败: {str(e)}")

    async def download_avatar(self, bot, wxid, from_wxid=None, force_update=False):
        """下载用户头像并保存到临时目录"""
        try:
            # 定义头像文件路径
            avatar_path = os.path.join(self.avatar_dir, f"{wxid}.jpg")
            
            # 创建缓存目录
            os.makedirs(self.avatar_dir, exist_ok=True)
            
            avatar_url = None
            avatar_source = "未知"
            
            # 1. 优先使用get_contact方法获取头像
            try:
                profile = await bot.get_contact(wxid)
                if profile and isinstance(profile, dict):
                    logger.info(f"获取到用户资料: {profile}")
                    if "BigHeadImgUrl" in profile and profile["BigHeadImgUrl"]:
                        avatar_url = profile["BigHeadImgUrl"]
                        avatar_source = "联系人信息"
                    elif "SmallHeadImgUrl" in profile and profile["SmallHeadImgUrl"]:
                        avatar_url = profile["SmallHeadImgUrl"]
                        avatar_source = "联系人信息"
            except Exception as e:
                logger.warning(f"通过get_contact获取头像失败: {str(e)}")
            
            # 2. 如果是群聊消息，尝试从群获取用户头像
            if not avatar_url and from_wxid and "@chatroom" in from_wxid:
                try:
                    # 获取群成员列表
                    group_members = await bot.get_chatroom_member_list(from_wxid)
                    logger.info(f"获取到群成员列表，共{len(group_members) if isinstance(group_members, list) else 0}个成员")
                    
                    if isinstance(group_members, list) and group_members:
                        # 查找目标用户
                        for member in group_members:
                            if isinstance(member, dict) and "UserName" in member and member["UserName"] == wxid:
                                logger.info(f"在群成员中找到目标用户: {member}")
                                # 提取头像URL
                                if "BigHeadImgUrl" in member and member["BigHeadImgUrl"]:
                                    avatar_url = member["BigHeadImgUrl"]
                                    avatar_source = "群成员列表"
                                    break
                                elif "SmallHeadImgUrl" in member and member["SmallHeadImgUrl"]:
                                    avatar_url = member["SmallHeadImgUrl"]
                                    avatar_source = "群成员列表"
                                    break
                
                except Exception as e:
                    logger.warning(f"从群成员列表获取头像失败: {str(e)}")
            
            # 3. 如果前两种方式都失败，尝试通过个人资料API获取
            if not avatar_url:
                try:
                    user_info = await bot.get_profile(wxid)
                    if user_info and isinstance(user_info, dict):
                        logger.info(f"获取到用户资料(get_profile): {user_info}")
                        # 尝试各种可能的头像字段名
                        for field in ["smallHeadImgUrl", "avatar", "avatarUrl", "headImgUrl"]:
                            if field in user_info and user_info[field]:
                                avatar_url = user_info[field]
                                avatar_source = "个人资料"
                                break
                
                except Exception as e:
                    logger.warning(f"通过个人资料获取头像失败: {str(e)}")
            
            # 如果获取不到头像URL，返回None
            if not avatar_url:
                logger.error(f"无法获取用户 {wxid} 的头像")
                return None
            
            # 下载头像
            logger.info(f"下载头像: {avatar_url} (来源: {avatar_source})")
            try:
                async with aiohttp.ClientSession() as session:
                    # 添加超时设置
                    timeout = aiohttp.ClientTimeout(total=10)
                    headers = {
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
                    }
                    
                    async with session.get(avatar_url, headers=headers, timeout=timeout) as resp:
                        if resp.status == 200:
                            # 直接保存到头像文件
                            with open(avatar_path, "wb") as f:
                                avatar_data = await resp.read()
                                f.write(avatar_data)
                            
                            # 检查下载的文件是否有效
                            if os.path.exists(avatar_path) and os.path.getsize(avatar_path) > 100:
                                logger.info(f"头像下载成功: {avatar_path}")
                                return avatar_path
                            else:
                                logger.error(f"下载的头像文件无效")
                                return None
                        else:
                            logger.error(f"下载头像失败，状态码: {resp.status}")
                            return None
            except Exception as e:
                logger.error(f"下载头像异常: {str(e)}")
                return None
                
        except Exception as e:
            logger.error(f"获取头像过程中发生错误: {str(e)}")
            return None

    async def send_emoji_list(self, bot, to_wxid):
        """发送表情列表"""
        single_emoji_list = list(self.single_emojis.keys())
        two_person_emoji_list = list(self.two_person_emojis.keys())
        
        response = "【单人表情】"
        response += "、".join(single_emoji_list) if single_emoji_list else "没有单人表情触发词"
        
        response += "\n\n【双人表情】"
        response += "、".join(two_person_emoji_list) if two_person_emoji_list else "没有双人表情触发词"
        
        await bot.send_text_message(to_wxid, response)

    async def handle_enable_disable_commands(self, bot, message):
        """处理表情的启用/禁用命令"""
        content = message.get("Content", "").strip()
        from_wxid = message.get("FromWxid", "")
        is_group = message.get("IsGroup", False)
        actual_user_id = message.get("ActualUserWxid", "")
        
        # 检查权限
        admin_users = self.get_admin_users()
        if actual_user_id not in admin_users:
            await bot.send_text_message(from_wxid, "只有管理员才有权执行此操作！")
            return
            
        # 解析命令
        match = re.match(r'^(全局)?(禁用|启用)表情\s+(.+)$', content)
        if not match:
            return
            
        is_global, action, emoji_name = match.groups()
        
        # 检查表情是否存在
        emoji_type = self.single_emojis.get(emoji_name)
        if not emoji_type and emoji_name not in self.two_person_emojis:
            await bot.send_text_message(from_wxid, "未找到指定的表情！")
            return
            
        group_id = from_wxid if is_group else None
        
        if is_global:  # 全局控制
            if action == "禁用":
                self.globally_disabled_emojis.add(emoji_name)
                await bot.send_text_message(from_wxid, f"已全局禁用表情：{emoji_name}")
            else:  # 启用
                self.globally_disabled_emojis.discard(emoji_name)
                await bot.send_text_message(from_wxid, f"已全局启用表情：{emoji_name}")
        else:  # 群组控制
            if group_id:
                if action == "禁用":
                    if group_id not in self.disabled_emojis:
                        self.disabled_emojis[group_id] = set()
                    self.disabled_emojis[group_id].add(emoji_name)
                    await bot.send_text_message(from_wxid, f"已在当前群禁用表情：{emoji_name}")
                else:  # 启用
                    if group_id in self.disabled_emojis:
                        self.disabled_emojis[group_id].discard(emoji_name)
                        await bot.send_text_message(from_wxid, f"已在当前群启用表情：{emoji_name}")
            else:
                await bot.send_text_message(from_wxid, "该命令只能在群聊中使用")
    
    def extract_at_users(self, content, message):
        """从消息内容中提取被@的用户wxid"""
        at_users = []
        
        # 输出原始消息内容中的AtUserList字段
        logger.info(f"原始消息AtUserList: {message.get('AtUserList', 'None')}, Ats: {message.get('Ats', 'None')}")
        
        # 从消息对象中提取被@用户
        if "AtUserList" in message and isinstance(message["AtUserList"], list):
            at_users = message["AtUserList"]
            logger.info(f"从AtUserList获取到的@用户: {at_users}")
        elif "Ats" in message and isinstance(message["Ats"], list):
            at_users = message["Ats"]
            logger.info(f"从Ats获取到的@用户: {at_users}")
        
        # 检查at_users是否为空
        if not at_users:
            logger.warning("未能从消息中提取到@用户")
        
        return at_users
    
    def clean_at_text(self, content):
        """移除所有@部分并返回清理后的字符串"""
        # 修改正则表达式，避免过度清理
        clean_content = re.sub(r'@[\u4e00-\u9fa5a-zA-Z0-9_\^\-~\*]+(?:\s*[\u4e00-\u9fa5a-zA-Z0-9_\^\-~\*]+)*\s*', '', content)
        result = clean_content.strip()
        logger.debug(f"原内容: '{content}', 清理后: '{result}'")
        return result
    
    def get_admin_users(self):
        """获取管理员用户列表"""
        try:
            # 首先尝试从全局配置文件获取管理员列表
            global_admins = []
            config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.json")
            if os.path.exists(config_path):
                try:
                    with open(config_path, 'r', encoding='utf-8') as f:
                        config = json.load(f)
                        
                    # 尝试获取管理员列表
                    if "admin_users" in config:
                        global_admins.extend(config["admin_users"])
                    if "admins" in config:
                        global_admins.extend(config["admins"])
                except Exception as e:
                    logger.warning(f"读取全局管理员配置失败: {str(e)}")
            
            # 合并全局管理员和本地管理员
            all_admins = set(global_admins + self.local_admin_users)
            return list(all_admins)
        except Exception as e:
            logger.error(f"获取管理员列表失败: {str(e)}")
            # 发生错误时返回本地管理员列表作为后备
            return self.local_admin_users
        
    async def async_init(self):
        """异步初始化函数"""
        pass

    @schedule('interval', hours=24)
    async def cleanup_avatar_cache(self, bot: WechatAPIClient):
        """定期清理头像缓存"""
        if not self.enable:
            return
            
        logger.info("开始清理头像缓存...")
        try:
            current_time = time.time()
            avatars_cleaned = 0
            total_files = 0
            
            # 获取所有缓存文件
            for filename in os.listdir(self.avatar_dir):
                total_files += 1
                filepath = os.path.join(self.avatar_dir, filename)
                
                # 跳过目录
                if os.path.isdir(filepath):
                    continue
                    
                # 检查是否是头像文件
                if filename.endswith('.jpg'):
                    wxid = filename[:-4]  # 移除.jpg后缀
                    
                    # 检查使用计数和最后更新时间
                    use_count_file = os.path.join(self.avatar_dir, f"{wxid}.count")
                    last_update_file = os.path.join(self.avatar_dir, f"{wxid}.update")
                    
                    should_remove = False
                    
                    # 如果存在使用计数文件，检查使用次数
                    if os.path.exists(use_count_file):
                        try:
                            with open(use_count_file, 'r') as f:
                                count = int(f.read().strip())
                                
                            # 如果使用次数少于配置的阈值，并且超过配置的天数未更新，删除文件
                            if count < self.cleanup_threshold and os.path.exists(last_update_file):
                                try:
                                    with open(last_update_file, 'r') as f:
                                        last_update = float(f.read().strip())
                                        
                                    if current_time - last_update > self.cleanup_expire_days * 86400:
                                        should_remove = True
                                except:
                                    pass
                        except:
                            pass
                    
                    # 执行清理
                    if should_remove:
                        try:
                            # 删除所有相关文件
                            for ext in ['.jpg', '.mark', '.update', '.count', '.tmp']:
                                ext_file = os.path.join(self.avatar_dir, f"{wxid}{ext}")
                                if os.path.exists(ext_file):
                                    os.remove(ext_file)
                                    avatars_cleaned += 1
                        except Exception as e:
                            logger.error(f"清理头像文件失败: {str(e)}")
            
            logger.info(f"头像缓存清理完成。共清理 {avatars_cleaned} 个文件，剩余 {total_files - avatars_cleaned} 个文件。")
        
        except Exception as e:
            logger.error(f"清理头像缓存过程中发生错误: {str(e)}")
            
    async def clear_avatar_cache(self, wxid):
        """清理特定用户的头像缓存"""
        files_removed = 0
        for ext in ['.jpg', '.mark', '.update', '.count', '.tmp']:
            ext_file = os.path.join(self.avatar_dir, f"{wxid}{ext}")
            if os.path.exists(ext_file):
                os.remove(ext_file)
                files_removed += 1
        return files_removed
        
    async def clear_all_avatar_cache(self):
        """清理所有头像缓存"""
        current_time = time.time()
        avatars_cleaned = 0
        
        # 获取所有缓存文件
        for filename in os.listdir(self.avatar_dir):
            filepath = os.path.join(self.avatar_dir, filename)
            
            # 跳过目录
            if os.path.isdir(filepath):
                continue
                
            # 清理所有临时文件
            if filename.endswith('.tmp'):
                os.remove(filepath)
                avatars_cleaned += 1
                continue
                
            # 检查是否是头像文件
            if filename.endswith('.jpg'):
                wxid = filename[:-4]  # 移除.jpg后缀
                
                # 检查是否超过3天未使用
                last_update_file = os.path.join(self.avatar_dir, f"{wxid}.update")
                if os.path.exists(last_update_file):
                    try:
                        with open(last_update_file, 'r') as f:
                            last_update = float(f.read().strip())
                            
                        # 如果超过3天未使用，删除文件
                        if current_time - last_update > 3 * 86400:  # 3天
                            for ext in ['.jpg', '.mark', '.update', '.count']:
                                ext_file = os.path.join(self.avatar_dir, f"{wxid}{ext}")
                                if os.path.exists(ext_file):
                                    os.remove(ext_file)
                                    avatars_cleaned += 1
                    except:
                        pass
        
        return avatars_cleaned 