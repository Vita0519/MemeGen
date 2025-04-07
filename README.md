# MemeGen - 表情包生成器插件

MemeGen是XYBotV2、xxxBot信机器人的一个表情包生成插件，可以在微信群聊中根据用户头像生成各种有趣的表情包。

## 功能特点

1. **他人单人表情**：@目标用户 + 触发词，使用被@用户的头像生成表情包
2. **双人表情包生成**：@用户A + 触发词 + @用户B，使用两位被@用户的头像生成互动表情
3. **表情列表查询**：查看所有可用的表情触发词
4. **表情启用/禁用**：管理员可控制特定表情的启用状态
5. **智能缓存管理**：自动缓存用户头像，减少重复下载

## 使用方法

### 基础命令

- **他人单人表情**：`@用户名 触发词`（如"@张三 摸"）- 使用被@用户的头像
- **双人表情**：`@用户A 触发词 @用户B`（如"@张三 亲 @李四"）- 使用两位被@用户的头像
- **查看表情列表**：发送"表情列表"或"表情菜单"

### 使用示例

- 发送"@张三 摸" → 使用张三的头像生成"摸"表情
- 发送"@张三 亲 @李四" → 生成张三亲李四的双人表情

## 安装要求

1. 安装meme-generator库：
   ```
   pip install -U meme_generator
   ```

2. 下载表情资源：
   ```
   meme download
   ```

## 配置说明

插件使用`emoji.json`配置文件来定义表情包触发词和类型：

```json
{
    "one_PicEwo": {
        "触发词1": "表情类型1",
        "触发词2": "表情类型2"
    },
    "two_PicEwo": {
        "触发词3": "双人表情类型1",
        "触发词4": "双人表情类型2"
    }
}
```

## 高级特性

### 智能缓存管理

- **头像缓存策略**：
  - 真实头像缓存24小时有效
  - 默认头像缓存12小时后尝试更新
  - 使用计数追踪：记录每个头像的使用次数
  - 自动清理：每24小时自动清理低使用率的缓存
  - 手动清理：管理员可以手动清理特定用户或所有缓存

- **缓存文件结构**：
  - `wxid.jpg`：用户头像文件
  - `wxid.mark`：标记文件（default/real）
  - `wxid.update`：最后更新时间记录
  - `wxid.count`：使用次数计数

## 注意事项

- 头像获取优先级：
  1. 直接获取联系人信息
  2. 从群成员列表获取
  3. 通过个人资料API获取
  4. 使用默认头像

- 权限控制：管理员命令仅限管理员使用
- 缺点：由于微信表情包缓存策略，生成的表情包只静态显示，复制后发送才会有动态效果

## 免责声明

本插件基于meme-generator库开发，所使用的表情资源版权归原作者所有。插件仅作娱乐用途，请勿用于商业目的或传播不良内容。 

## 联系方式

<div align="center"><table><tbody><tr><td align="center"><b>个人QQ</b><br><img src="https://wmimg.com/i/1119/2025/02/67a96bb8d3ef6.jpg" width="250" alt="作者QQ"><br><b>QQ：154578485</b></td><td align="center"><b>QQ交流群</b><br><img src="https://wmimg.com/i/1119/2025/02/67a96bb8d6457.jpg" width="250" alt="QQ群二维码"><br><small>群内会更新个人练手的python项目</small></td><td align="center"><b>微信赞赏</b><br><img src="https://wmimg.com/i/1119/2024/09/66dd37a5ab6e8.jpg" width="500" alt="微信赞赏码"><br><small>要到饭咧？啊咧？啊咧？不给也没事~ 请随意打赏</small></td><td align="center"><b>支付宝赞赏</b><br><img src="https://wmimg.com/i/1119/2024/09/66dd3d6febd05.jpg" width="300" alt="支付宝赞赏码"><br><small>如果觉得有帮助,来包辣条犒劳一下吧~</small></td></tr></tbody></table></div>

---

### 📚 推荐阅读

-   [wx群聊总结助手：一个基于人工智能的微信群聊消息总结工具，支持多种AI服务，可以自动提取群聊重点内容并生成结构化总结](https://github.com/Vita0519/wechat_summary)
-   [历时两周半开发的一款加载live2模型的浏览器插件](https://www.allfather.top/archives/live2dkan-ban-niang)
-   [PySide6+live2d+小智 开发的 AI 语音助手桌面精灵，支持和小智持续对话、音乐播放、番茄时钟、书签跳转、ocr等功能](https://www.bilibili.com/video/BV1wN9rYFEze/?share_source=copy_web&vd_source=f3d1033524bcd51cf10e8312ef8376ff)
-   [github优秀开源作品集](https://www.allfather.top/mol2d/)

---