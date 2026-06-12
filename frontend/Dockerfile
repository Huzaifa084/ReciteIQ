FROM node:24-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --silent
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
# TLS certs + site config are bind-mounted by compose (house pattern: app-level
# nginx terminates TLS on a loopback port behind the edge SNI router)
