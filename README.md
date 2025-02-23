## 主要功能
爬取欧陆词典网页版的数据，获取最近添加的生词作为卡片正面
从本地柯林斯词典（.mdx）获取生词对应的释义作为卡片背面
如果某个单词在柯林斯词典中查询不到，则调用Deepseek API获取释义，生成与柯林斯词典格式类似的释义作为背面
组合成卡片并上传到本地指定的Anki牌组中
一键打包为AWSLambda部署所需的压缩包，使用Lambda定期（如每天）执行

## 需要自己定义的变量
NEW_WORDS_PERIOD：获取最近添加生词的天数
EUDICT_WEB_COOKIE：欧陆词典cookie，若空则跳出登录界面手动登录
AI_API_KEY：SillionCloud API token，用于调用Deepseek V3 模型
ANKI_DECK_NAME：要添加卡片的牌组名称，需确保该卡片已在Anki中建立

## 本地运行
在config.py中填写变量
安装requirements.txt中所需依赖
确保Anki已安装了AnkiConnect，且Anki客户端处于运行状态
执行python main_local.py
自动输出成功添加的单词数量及单词清单，若有未成功添加的单词也会输出单词清单和失败原因
