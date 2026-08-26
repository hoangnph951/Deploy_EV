# ---- Stage 1: Build React/Vite ----
FROM node:20-alpine AS builder

WORKDIR /workspace/src/apps/web

COPY package*.json ./
RUN npm ci

COPY . .

ARG VITE_API_BASE_URL
ARG VITE_GOONG_MAPTILES_KEY

ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}
ENV VITE_GOONG_MAPTILES_KEY=${VITE_GOONG_MAPTILES_KEY}

RUN npm run build


# ---- Stage 2: Serve with Nginx ----
FROM nginx:alpine

COPY --from=builder /workspace/build/web /usr/share/nginx/html

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]