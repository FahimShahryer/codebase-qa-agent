FROM node:20-alpine

WORKDIR /app

# Install deps (cached layer)
COPY package.json package-lock.json* ./
RUN npm install

# Copy source (also bind-mounted at runtime for hot reload)
COPY . .

EXPOSE 3000

# `next dev` watches files; bind-mount in docker-compose drives reloads
CMD ["npm", "run", "dev"]
