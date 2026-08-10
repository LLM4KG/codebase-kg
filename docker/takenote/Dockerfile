FROM node:14-bullseye

ENV HUSKY=0
ENV CYPRESS_INSTALL_BINARY=0
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 make g++ && rm -rf /var/lib/apt/lists/*

COPY package.json package-lock.json ./
RUN npm ci --silent

COPY . .

# `stage_build_context()` excludes .git, so /app arrives as a plain directory.
# `git apply` works without a repo, but `applied.patch` and the install gate do
# not — initialise one with a baseline commit. The upstream .gitignore is
# present (only .git was excluded), so node_modules stays out of the index.
RUN git init -q . \
    && git config user.email "harness@local" \
    && git config user.name "codebase-kg harness" \
    && git add -A \
    && git commit -q --allow-empty -m "harness baseline"

COPY docker/entrypoint.sh /harness/entrypoint.sh
COPY docker/apply_edits.js /harness/apply_edits.js
RUN chmod +x /harness/entrypoint.sh

ENTRYPOINT ["/harness/entrypoint.sh"]
