---
name: repo
agent: CodeActAgent
triggers:
  - keyword: ""
---

# VibeWebAgent Repository

You are working on **VibeWebAgent**, the core browser automation agent for VibeTechnologies.

## Project Overview

VibeWebAgent is a Chrome extension and web automation platform that enables AI-powered browser control. It uses the Playwright MCP server pattern for reliable web automation.

## Tech Stack

- **Language**: TypeScript
- **Framework**: React (popup UI), Chrome Extension APIs
- **Package Manager**: npm
- **Test Framework**: Jest + Playwright
- **Build Tool**: Vite

## Development Commands

```bash
# Install dependencies
npm install

# Run tests
npm test

# Run linting
npm run lint

# Build extension
npm run build

# Development mode
npm run dev
```

## Code Style Guidelines

- Use TypeScript strict mode
- Follow React functional component patterns
- Use Tailwind CSS for styling
- Prefer async/await over .then() chains
- Keep components small and focused

## Important Files

- `manifest.json` - Chrome extension manifest (v3)
- `src/background/` - Service worker scripts
- `src/content/` - Content scripts for page injection
- `src/popup/` - Extension popup UI
- `src/lib/` - Shared utilities

## Common Patterns

### Message Passing
```typescript
// Send message from popup to background
chrome.runtime.sendMessage({ type: 'ACTION', payload: data });

// Listen in background
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.type === 'ACTION') { /* handle */ }
});
```

### Content Script Injection
```typescript
await chrome.scripting.executeScript({
  target: { tabId },
  files: ['content.js']
});
```

## Debugging Tips

- Use `chrome://extensions` to reload and inspect the extension
- Check the service worker console for background script logs
- Use React DevTools for popup debugging
- Network requests are visible in the extension's DevTools Network tab
