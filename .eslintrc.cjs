// Stub ESLint config — slice 5 (api-foundation-rfc7807) + slice W1
// (dashboard-svelte-skeleton) flesh this out with real rules. For now we
// declare the shape so pre-commit's eslint hook can no-op until source
// code lands under apps/web/ or packages/shared-types/.
module.exports = {
  root: true,
  env: {
    node: true,
    es2022: true,
  },
  parserOptions: {
    ecmaVersion: 2022,
    sourceType: 'module',
  },
  ignorePatterns: [
    'node_modules/',
    'dist/',
    '.svelte-kit/',
    '.skills-sources/',
    '.ai-playbook/',
    'skills/',
    '.claude/',
    '.gemini/',
    '.venv/',
  ],
  rules: {},
};
