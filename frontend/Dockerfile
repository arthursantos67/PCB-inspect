# Three stages for two very different jobs:
#
#   dev     — `next dev` against a bind-mounted checkout (docker-compose.dev.yml). Hot reload
#             actually works, so editing a file no longer means rebuilding an image.
#   runner  — the shipped image: `next build` output, served by Next's standalone server. The
#             default target, so `docker compose build` produces the production artifact.
#
# The old single stage did neither: it baked the source into the image and then ran `next dev`
# against that frozen copy, paying dev mode's on-demand compilation without ever getting the
# hot reload that justifies it.

FROM node:22-slim AS deps
WORKDIR /srv
ENV NEXT_TELEMETRY_DISABLED=1
COPY package.json package-lock.json ./
RUN npm ci

# ---- development -----------------------------------------------------------------------
# Source is mounted at runtime, not copied — see docker-compose.dev.yml, which also keeps
# /srv/node_modules and /srv/.next as container-owned volumes so the host checkout never
# shadows the dependencies installed above.
FROM deps AS dev
EXPOSE 3000
CMD ["npm", "run", "dev"]

# ---- production build ------------------------------------------------------------------
FROM deps AS builder
COPY . .
# Webpack rather than the `--turbopack` flag `npm run build` carries: standalone output is not
# produced by the Turbopack builder on Next 15.5, and this image is exactly the thing that
# needs it.
ENV NEXT_OUTPUT_STANDALONE=1
RUN npx next build

FROM node:22-slim AS runner
WORKDIR /srv
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0
# `node` (uid 1000) ships with the base image; the server needs no write access to anything
# it owns, so it runs unprivileged.
COPY --from=builder --chown=node:node /srv/.next/standalone ./
COPY --from=builder --chown=node:node /srv/.next/static ./.next/static
USER node
EXPOSE 3000
CMD ["node", "server.js"]
