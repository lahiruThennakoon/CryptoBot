FROM node:20-alpine AS build
WORKDIR /app
# Baked into the client bundle at build time (browser calls your tunneled localhost).
ARG NEXT_PUBLIC_API_URL=http://127.0.0.1:8000
ARG NEXT_PUBLIC_API_TOKEN=
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
ENV NEXT_PUBLIC_API_TOKEN=$NEXT_PUBLIC_API_TOKEN
COPY package.json ./
RUN npm install
COPY . .
RUN npm run build

FROM node:20-alpine
WORKDIR /app
ENV NODE_ENV=production
COPY --from=build /app/.next ./.next
COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/package.json ./
EXPOSE 3000
CMD ["npm", "start"]
