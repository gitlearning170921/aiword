宿主机 nginx 配置说明（非 Docker 容器）

生产 compose 不包含 nginx 镜像/容器。请将本目录 nginx.conf 中的 server 段
复制到服务器 /etc/nginx/conf.d/aiword.conf，并：

  proxy_pass http://127.0.0.1:5000;

确保 docker-compose.prod.yml 已映射 aiword 到 127.0.0.1:5000。

应用：sudo nginx -t && sudo systemctl reload nginx
