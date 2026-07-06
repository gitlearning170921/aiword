git-tag_release — 发版（打 tag，供打包机按 v版本 拉代码）

  release.bat 1.0.5 "发版说明"

  同时处理 aiword + 同级 aicheckword：
    push 代码 -^> 打 tag v1.0.5 -^> push tag

日常开发请用 git-no_tag\ 下的脚本（不打 tag）。
