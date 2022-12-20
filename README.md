SYAK:同步 SiYuan 内容块到 Anki, 自动更新, 自动删除

> 如果觉得有帮助, 麻烦点个 Star⭐
>

# Prerequisite

1. Anki 需要安装 AnkiConnect 插件, code 为 `2055492159`​​, 默认端口 `8765`​​
2. 支持 Python 3.9 以上版本
3. SiYuan 默认端口为 `6806`​​
4. 同步时, 保持 SiYuan 和 Anki 同时运行

# Install

```
pip install syak
```

# Usage

1. 新建一个 `card`​ ​文档块, 名字支持前后缀, 例如 `@card`​​
2. 在需要制卡的内容块后面引用 `card`​ ​文档块
3. 制卡内容块为某个容器块下的叶子块时, 卡片正面为制卡内容块, 背面为整个容器块
4. 制卡内容块为文档块下的叶子块时, 卡片正面制卡内容块, 背面为空
5. 运行命令 `syak -p SiYuan数据根路径(data目录的上一级)`​ ​即可同步
6. 查看更多选项运行 `syak -h`​​

# DEMO

​![demo](demo.gif)​

# Feature

1. 添加 SiYuan URL 跳转链接
2. 自动更新, SiYuan 更新内容块后, Anki 自动更新
3. 自动删除, 删除 `card`​ ​引用块, Anki 自动删除
4. 根据文档块层级自动建立 deck 层级
5. 支持 media 文件
6. 自动删除 empty deck
7. 同步完成时, 发送同步信息给 SiYuan, 停留 5s

# Not Support (currently)

1. Close
2. 代码块高亮
3. 超级块未适配

# MORE

使用带有定时运行脚本功能的软件,如 [Keyboard Maestro](https://www.keyboardmaestro.com/main/) 或者 [Quicker](https://getquicker.net/) 实现后台无缝同步

‍