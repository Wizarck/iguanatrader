# Tasks: research-frontend-storybook

- [ ] 1. `pnpm add -D storybook @storybook/sveltekit @storybook/addon-a11y` in `apps/web/`
- [ ] 2. `.storybook/main.ts` + `.storybook/preview.ts`
- [ ] 3. `MethodologyBadge.stories.ts` (8 variants)
- [ ] 4. `CitationLink.stories.ts` (5 variants)
- [ ] 5. `BriefHeader.stories.ts` (4 variants)
- [ ] 6. `FactTimeline.stories.ts` (5 variants)
- [ ] 7. `AuditTrailViewer.stories.ts` (4 variants)
- [ ] 8. Add `storybook` + `build-storybook` scripts to `package.json`
- [ ] 9. `tsconfig.json` exclude for `**/*.stories.ts`
- [ ] 10. `.gitignore` for `storybook-static/`
- [ ] 11. Verify `pnpm build-storybook` succeeds locally
- [ ] 12. Verify `pnpm check` clean (0 errors) + `pnpm test` (28/28)
- [ ] 13. Push + open PR + wait CI green
- [ ] 14. Merge + archive + retro fill
