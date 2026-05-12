import type { StorybookConfig } from '@storybook/sveltekit';

const config: StorybookConfig = {
  stories: ['../src/lib/**/*.stories.@(js|ts|svelte)'],
  addons: ['@storybook/addon-a11y'],
  framework: {
    name: '@storybook/sveltekit',
    options: {}
  },
  typescript: {
    check: false
  }
};

export default config;
