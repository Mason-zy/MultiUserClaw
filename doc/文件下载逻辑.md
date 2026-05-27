 前端的匹配规则在 FileDownloadPlugin.tsx 中，逻辑如下：

   文件路径识别规则

   isFilePath() 函数（第 45-56 行）决定一个链接是否显示为可下载文件：

   OpenClaw workspace 路径（走 filemanager/download）：
     - 正则：OPENCLAW_PATH_RE（第 37-38 行）
     - 匹配：workspace/file.pdf、~/.openclaw/workspace/report.docx、media/images/pic.png
   绝对路径（走 filemanager/serve）：
     - 正则：ABSOLUTE_PATH_RE（第 41-42 行）：~?(?:\/[\w._-]+)+\/[\w.\-\u4e00-\u9fff]+\.\w{1,10}
     - 并且扩展名必须在 FILE_EXTENSIONS 集合中（第 25-32 行）

   为什么有的文件能显示，有的不能？

   能被识别为下载链接的条件：
   - 扩展名必须在 FILE_EXTENSIONS 这个白名单里

   当前的扩展名白名单：
    1 文档类：pdf, doc, docx, xls, xlsx, csv, ppt, pptx, txt, md, json, xml, yaml, yml, toml
    2 图片类：png, jpg, jpeg, gif, svg, webp, bmp
    3 压缩类：zip, tar, gz, rar, 7z
    4 媒体类：mp3, wav, mp4, avi, mov
    5 代码类：py, js, ts, html, css

# 后端
不同的下载目录可下载
platform/app/runtime_backends/hermes_files.py
