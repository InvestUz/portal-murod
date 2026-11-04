// Tooling configuration only; no JavaScript backend is shipped or executed.
import js from '@eslint/js';
import tseslint from 'typescript-eslint';
export default tseslint.config(
  {ignores:['frontend-dist/**','node_modules/**']},
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {files:['apps/web/**/*.{ts,tsx}'],rules:{'@typescript-eslint/no-unused-vars':['error',{argsIgnorePattern:'^_',varsIgnorePattern:'^_'}]}}
);
