# WoolGate Plugin Development Guide

This guide covers everything you need to build plugins for WoolGate. Start with the **Quick Start** below, then dive into the detailed references.

## Quick Start (30 seconds)

```python
from app.extensions.sdk import register_hook, register_page

PLUGIN_NAME = "my_plugin"
PLUGIN_VERSION = "1.0.0"

@register_hook("route.before")
async def my_hook(ctx):
    ctx.set("my_plugin.touched", True)

@register_page("/my-plugin", title="My Plugin")
def my_page(request):
    from nicegui import ui
    ui.label("Hello from my plugin!")
```

Enable via environment variable:
```bash
WOOLGATE_PLUGINS=plugins.my_plugin
```

See [`plugins/hello_world.py`](../../plugins/hello_world.py) for a complete, annotated example.

## Extension Mechanisms

WoolGate provides three extension mechanisms:

### 1. Lifecycle Hooks
Intercept and modify requests/responses at 9 pipeline stages.

→ [02-hooks-spi.md](02-hooks-spi.md) — Full hook reference with examples

### 2. SPI (Strategy Provider Interface)
Replace core strategy implementations (classifier, router, selector, context, security, adapter, store).

→ [02-hooks-spi.md](02-hooks-spi.md) — SPI registration and usage

### 3. UI Injection Slots
Extend the admin panel visually (dashboard widgets, account card footer, log detail, custom pages, custom nav items).

→ [03-plugin-sdk.md](03-plugin-sdk.md) — UI injection API reference

## Detailed References

| Document | Content |
|---|---|
| [01-context-object.md](01-context-object.md) | PluginContext API — read/write request state, set routing decisions |
| [02-hooks-spi.md](02-hooks-spi.md) | 9 lifecycle hooks + 7 SPI types, with code examples |
| [03-plugin-sdk.md](03-plugin-sdk.md) | Full SDK reference: register_hook, register_spi, register_page, register_nav_item, register_component, register_config |
| [04-classifier-engine.md](04-classifier-engine.md) | How the classification engine works and how to replace it via SPI |
| [05-client-adapters.md](05-client-adapters.md) | Client adapter SPI — support protocols beyond OpenAI-compatible |
| [06-tenant-isolation.md](06-tenant-isolation.md) | Multi-tenant isolation design (Enterprise Edition) |

## Plugin Lifecycle

1. **Discovery** — WoolGate reads `WOOLGATE_PLUGINS` env var (comma-separated module paths)
2. **Import** — Each module is imported; registration decorators (`@register_hook`, etc.) execute at import time
3. **Activation** — Registered hooks/SPIs/UI slots are active immediately
4. **Failure isolation** — If a plugin fails to import, it is skipped with a warning; other plugins and the gateway continue to work

## Best Practices

- **Always define** `PLUGIN_NAME` and `PLUGIN_VERSION` constants
- **Use `ctx.set()` / `ctx.get()`** instead of directly modifying `ctx.extensions`
- **Pass `plugin_name=PLUGIN_NAME`** to `register_config()` for correct config namespacing
- **Keep plugins stateless** where possible; use `ctx.set()` for per-request state
- **Handle errors gracefully** — a plugin exception should not crash the gateway
