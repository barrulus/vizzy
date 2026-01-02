# Vizzy Accessibility Guide

## Overview

Vizzy is committed to providing an accessible experience for all users. This document describes the accessibility features implemented as part of Phase 8H-004 (Accessibility audit and fixes) and provides guidance for developers maintaining accessibility standards.

## WCAG 2.1 AA Compliance

Vizzy targets WCAG 2.1 Level AA compliance. The following sections detail how each guideline is addressed.

---

## 1. Keyboard Navigation

All interactive elements in Vizzy are keyboard accessible.

### Global Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `/` | Focus search input |
| `Escape` | Close modal / blur input / go back |
| `g h` | Go to home page |
| `g e` | Go to explore view |
| `j` / `ArrowDown` | Next item in list |
| `k` / `ArrowUp` | Previous item in list |
| `Enter` | Open selected item |
| `o` | Open selected item in new tab |
| `?` | Show keyboard shortcuts help |

### Analysis Shortcuts (when viewing an import)

| Key | Action |
|-----|--------|
| `d` | View duplicate packages |
| `p` | Open path finder |
| `l` | View circular dependencies (loops) |
| `r` | View redundant links |
| `w` | Why Chain (attribution) |

### Graph Navigation

| Key | Action |
|-----|--------|
| `+` / `=` | Zoom in |
| `-` | Zoom out |
| `0` | Reset view |

### Treemap Navigation

| Key | Action |
|-----|--------|
| `Arrow keys` | Navigate between cells |
| `Enter` / `Space` | Zoom into selected cell |
| `Escape` | Zoom out one level |
| `Home` | Reset to root view |
| `Backspace` | Go back one level |
| `r` | Toggle runtime filter |
| `b` | Toggle build-time filter |

---

## 2. Screen Reader Support

### Live Regions

Vizzy uses ARIA live regions to announce dynamic content changes to screen reader users:

- **Polite announcements** (`aria-live="polite"`): Used for loading states, search results counts, and navigation updates
- **Assertive announcements** (`aria-live="assertive"`): Used for errors and critical alerts

### Landmarks

The application structure uses semantic HTML and ARIA landmarks:

```html
<nav aria-label="Primary navigation">...</nav>
<nav aria-label="Skip navigation">...</nav>
<nav aria-label="Configuration views">...</nav>
<main id="main-content" role="main">...</main>
```

### Skip Links

Skip links allow users to bypass repetitive navigation:

- **Skip to main content**: Jump directly to the main content area
- **Skip to search**: Jump to the search results area (when applicable)

### Dynamic Content

When HTMX loads new content:

1. The target element receives `aria-busy="true"` during loading
2. After loading completes, screen readers are notified via live region
3. Focus is managed appropriately for modal dialogs

---

## 3. Visual Design

### Focus Indicators

All focusable elements have visible focus indicators:

```css
:focus-visible {
    outline: 2px solid #3b82f6;
    outline-offset: 2px;
}
```

Enhanced focus for buttons and links:
```css
button:focus-visible,
a:focus-visible {
    outline: 3px solid #3b82f6;
    outline-offset: 2px;
    box-shadow: 0 0 0 4px rgba(59, 130, 246, 0.25);
}
```

### Color Contrast

Text colors are designed to meet WCAG AA contrast requirements (4.5:1 for normal text):

- Primary text: `#1e293b` on white background
- Secondary text: `#4b5563` on white background (adjusted from lighter grays)
- Error text: `#b91c1c` on light background
- Success text: `#047857` on light background
- Warning text: `#b45309` on light background

### Color Independence

Information is not conveyed by color alone:

- Error states include icons and text descriptions
- Graph nodes use both color and labels
- Status indicators include text labels

### High Contrast Mode

Vizzy supports Windows High Contrast Mode and `prefers-contrast: high`:

```css
@media (prefers-contrast: high) {
    :focus-visible {
        outline-width: 3px !important;
        outline-color: Highlight !important;
    }

    a {
        text-decoration: underline !important;
    }
}
```

---

## 4. Motion and Animation

### Reduced Motion Support

Vizzy respects the user's motion preferences:

```css
@media (prefers-reduced-motion: reduce) {
    *,
    *::before,
    *::after {
        animation-duration: 0.01ms !important;
        animation-iteration-count: 1 !important;
        transition-duration: 0.01ms !important;
    }
}
```

This applies to:
- Loading spinners
- Pulse animations
- Treemap zoom transitions
- Navigation loading indicators
- Tooltip animations

---

## 5. Forms and Input

### Form Labels

All form inputs have associated labels:

```html
<label for="upload-name">Name</label>
<input type="text" id="upload-name" name="name" required aria-required="true">
```

### Required Fields

Required fields are indicated with:
- `required` HTML attribute
- `aria-required="true"`

### Error Messages

Form errors are announced to screen readers:

```html
<input aria-invalid="true" aria-describedby="error-message">
<div id="error-message" role="alert">Error description</div>
```

### Search Inputs

Search inputs have proper labeling:

```html
<input type="search"
       aria-label="Search packages"
       name="q"
       placeholder="Search packages...">
```

---

## 6. Interactive Components

### Buttons

Buttons have accessible names:

```html
<button aria-label="Delete configuration-name" title="Delete">
    <svg aria-hidden="true">...</svg>
</button>
```

### Graph Controls

Graph zoom controls are grouped and labeled:

```html
<div role="group" aria-label="Graph zoom controls">
    <button aria-label="Zoom in">+</button>
    <button aria-label="Zoom out">-</button>
    <button aria-label="Reset view">Reset</button>
</div>
```

### Treemap Cells

Interactive treemap cells have ARIA attributes:

```html
<rect role="button"
      aria-label="firefox, 2340 derivations"
      tabindex="0">
</rect>
```

### Tooltips

Tooltips are marked with `role="tooltip"` and `aria-hidden` when not visible.

### Modals

Modal dialogs use proper ARIA attributes:

```html
<div role="dialog"
     aria-modal="true"
     aria-labelledby="modal-title">
    <h2 id="modal-title">Modal Title</h2>
    ...
</div>
```

Focus is trapped within open modals and returns to the trigger element on close.

---

## 7. Touch Targets

For touch devices (`pointer: coarse`), interactive elements have minimum 44x44px touch targets:

```css
@media (pointer: coarse) {
    button, a, [role="button"] {
        min-height: 44px;
        min-width: 44px;
    }
}
```

---

## Developer Guidelines

### Adding New Components

When adding new interactive components:

1. **Ensure keyboard access**: All interactive elements must be focusable and operable via keyboard
2. **Add ARIA labels**: Use `aria-label` or `aria-labelledby` for elements without visible text
3. **Mark decorative elements**: Use `aria-hidden="true"` for purely decorative icons
4. **Use semantic HTML**: Prefer native HTML elements (button, a, input) over divs with click handlers
5. **Test with screen reader**: Verify the component works with VoiceOver (macOS), NVDA/JAWS (Windows), or Orca (Linux)

### HTMX Content Updates

When using HTMX:

1. Add `aria-busy="true"` to loading targets:
   ```html
   <div hx-trigger="load" aria-busy="true">Loading...</div>
   ```

2. Include loading announcements:
   ```javascript
   window.vizzyA11y.announceLoading('search results');
   ```

3. Announce completion:
   ```javascript
   window.vizzyA11y.announceComplete('Search');
   ```

### Testing Checklist

Before submitting changes:

- [ ] All interactive elements are keyboard accessible
- [ ] Focus order is logical
- [ ] Focus indicators are visible
- [ ] Color is not the only means of conveying information
- [ ] Text contrast meets WCAG AA (4.5:1)
- [ ] Forms have proper labels and error handling
- [ ] Dynamic content changes are announced to screen readers
- [ ] Animations respect `prefers-reduced-motion`
- [ ] Touch targets are at least 44x44px on mobile

---

## Resources

- [WCAG 2.1 Guidelines](https://www.w3.org/WAI/WCAG21/quickref/)
- [WAI-ARIA Authoring Practices](https://www.w3.org/WAI/ARIA/apg/)
- [Inclusive Components](https://inclusive-components.design/)
- [A11y Project Checklist](https://www.a11yproject.com/checklist/)

---

## Files Modified

The following files were created or modified for accessibility:

### New Files
- `/static/css/accessibility.css` - Core accessibility styles
- `/static/js/accessibility.js` - Screen reader announcements and focus management
- `/docs/ACCESSIBILITY.md` - This documentation

### Modified Files
- `/src/vizzy/templates/base.html` - Skip links, live regions, accessibility.js/css includes
- `/src/vizzy/templates/index.html` - Form labels, button ARIA labels
- `/src/vizzy/templates/treemap.html` - ARIA labels for controls and cells
- `/static/js/graph-navigation.js` - ARIA labels for zoom controls
- `/static/css/keyboard.css` - High contrast and reduced motion support (existing)
