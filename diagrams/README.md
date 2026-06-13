# System Diagrams

Auto-generated diagrams for the Autonomous Treasury Agent. See the
[main README](../README.md) for the project overview.

> Note: icons are embedded as data-URIs and render in any direct SVG viewer. On
> GitHub's Markdown view the logos may be stripped by the sanitizer, but the
> shapes, colors, labels, and connections still render correctly.

---

## Architecture

### Overview (Simplified)
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="./architecture-simplified-dark.svg">
  <source media="(prefers-color-scheme: light)" srcset="./architecture-simplified-light.svg">
  <img alt="Architecture Overview" src="./architecture-simplified-light.svg">
</picture>

[View simplified documentation](./architecture-simplified.md)

### Detailed
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="./architecture-dark.svg">
  <source media="(prefers-color-scheme: light)" srcset="./architecture-light.svg">
  <img alt="Architecture Diagram" src="./architecture-light.svg">
</picture>

[View detailed documentation](./architecture.md)

---

## Infrastructure

### Overview (Simplified)
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="./infrastructure-simplified-dark.svg">
  <source media="(prefers-color-scheme: light)" srcset="./infrastructure-simplified-light.svg">
  <img alt="Infrastructure Overview" src="./infrastructure-simplified-light.svg">
</picture>

[View simplified documentation](./infrastructure-simplified.md)

### Detailed
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="./infrastructure-dark.svg">
  <source media="(prefers-color-scheme: light)" srcset="./infrastructure-light.svg">
  <img alt="Infrastructure Diagram" src="./infrastructure-light.svg">
</picture>

[View detailed documentation](./infrastructure.md)

---

## Documentation

| Document | Description |
|----------|-------------|
| [architecture-simplified.md](./architecture-simplified.md) | High-level architecture overview |
| [architecture.md](./architecture.md) | Detailed software architecture |
| [infrastructure-simplified.md](./infrastructure-simplified.md) | High-level infrastructure overview |
| [infrastructure.md](./infrastructure.md) | Detailed infrastructure components |

## Regenerating

```
/d2:diagram               # Full regeneration
/d2:diagram --incremental # Only changed components
```
