# bult preset: Express (Node.js).
# Your repository needs: package.json with "main" pointing to the entry file,
# and package-lock.json; the app must listen on process.env.PORT.
# Demo: examples/express-hello.

FROM node:24-slim AS builder

WORKDIR /app

COPY package*.json ./

RUN npm ci --omit=dev && npm cache clean --force



FROM node:24-slim AS runner

WORKDIR /app

ENV NODE_ENV=production \
    PORT=3000

COPY --from=builder --chown=node:node /app/node_modules ./node_modules
COPY --chown=node:node . .

USER node

EXPOSE ${PORT}

CMD ["node", "."]
