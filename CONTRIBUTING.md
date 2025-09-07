# Contributing to whl2conda

## Setting up development environment

This project uses [pixi](https://pixi.sh/) for development environment management.

> **Note**: This project recently migrated from conda to pixi for improved 
> development experience. If you have an old conda environment (`whl2conda-dev`), 
> you can remove it with `conda env remove -n whl2conda-dev`.

### Prerequisites

1. Install pixi following the [installation guide](https://pixi.sh/latest/#installation)

### Quick Setup

```bash
# Clone the repository
git clone <repository-url>
cd whl2conda

# Install the development environment
pixi install
pixi run dev-install
```

### Development Workflow

Common development tasks:

```bash
# Run tests
pixi run test

# Run linting and type checking
pixi run lint

# Build documentation
pixi run doc

# See all available tasks
pixi task list
```

### Environment Management

- **Install/update environment**: `pixi install`
- **Update dependencies**: `pixi update`
- **Environment isolation**: pixi automatically manages environment activation

### Key Development Commands

| Task | Command | Description |
|------|---------|-------------|
| Install dev environment | `pixi run install` | Set up complete development environment |
| Run tests | `pixi run test` | Execute test suite |
| Type checking | `pixi run mypy` | Run mypy type checking |
| Linting | `pixi run lint` | Run all linting checks |
| Format checking | `pixi run check-format` | Check code formatting |
| Build packages | `pixi run build` | Build wheel and conda packages |
| Generate docs | `pixi run doc` | Build documentation |
| Clean artifacts | `pixi run clean` | Remove generated files |

For a complete list of available tasks, run `pixi task list`.

## Project Structure

The project uses a modern Python packaging setup with:
- **Environment management**: pixi
- **Build system**: hatchling
- **Testing**: pytest with coverage
- **Linting**: ruff + mypy
- **Documentation**: MkDocs with Material theme

## Making Changes

1. Create a new branch for your changes
2. Make your modifications
3. Run tests: `pixi run test`
4. Check linting: `pixi run lint`
5. Update documentation if needed
6. Submit a pull request
