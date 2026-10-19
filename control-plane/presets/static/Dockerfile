# bult preset: static site / SPA (Node build, nginx serving).
# Your repository needs: package.json with a "build" script, package-lock.json;
# the build must write the site to dist/. Unknown paths fall back to index.html
# (client-side routing). Demo: examples/react-todos.

FROM node:22-alpine AS builder

WORKDIR /app

COPY package*.json ./

RUN npm ci

COPY . .

RUN npm run build


FROM nginx:1.28-alpine AS runner

ENV PORT=8000

# The server block is a template: the nginx image substitutes ${PORT} at start
# (envsubst leaves nginx's own $uri alone). Written with printf: the platform's
# builder has no heredoc support.
RUN rm /etc/nginx/conf.d/default.conf && mkdir -p /etc/nginx/templates && \
    printf '%s\n' \
        'server {' \
        '    listen ${PORT};' \
        '    root /usr/share/nginx/html;' \
        '    gzip on;' \
        '    gzip_types text/css application/javascript application/json image/svg+xml;' \
        '' \
        '    # hashed build output never changes under the same name' \
        '    location ~ ^/(assets|static)/ {' \
        '        add_header Cache-Control "public, max-age=31536000, immutable";' \
        '        try_files $uri =404;' \
        '    }' \
        '' \
        '    location = /index.html {' \
        '        add_header Cache-Control "no-cache";' \
        '    }' \
        '' \
        '    # client-side routes: unknown paths get the app shell' \
        '    location / {' \
        '        try_files $uri /index.html;' \
        '    }' \
        '}' \
        > /etc/nginx/templates/default.conf.template

COPY --from=builder /app/dist /usr/share/nginx/html

# Non-root: the entrypoint writes the rendered config and nginx its cache and pid file.
RUN touch /run/nginx.pid && \
    chown -R nginx:nginx /run/nginx.pid /var/cache/nginx /etc/nginx/conf.d

USER nginx

EXPOSE ${PORT}

CMD ["nginx", "-g", "daemon off;"]
