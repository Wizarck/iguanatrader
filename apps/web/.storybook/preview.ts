import type { Preview } from '@storybook/sveltekit';

const preview: Preview = {
  parameters: {
    controls: {
      matchers: {
        color: /(background|color)$/i,
        date: /Date$/i
      }
    },
    a11y: {
      // Slice W1 enforces a11y >= 95 in Lighthouse CI; surface the
      // axe-core violations inline in Storybook so component work
      // catches them before they hit the page.
      element: '#storybook-root',
      manual: false
    }
  }
};

export default preview;
