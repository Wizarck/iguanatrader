# Contributing to iguanatrader

iguanatrader is a single-maintainer project at MVP stage (pre-`v1.0.0`). Contribution guidelines will be fleshed out post-MVP.

For now:

- **Bug reports / feature requests**: open a [GitHub issue](https://github.com/Wizarck/iguanatrader/issues).
- **Security issues**: see [SECURITY.md](SECURITY.md). Do NOT open public issues for security.
- **Pull requests**: discuss the change in an issue first; for non-trivial work expect to follow the BMAD+OpenSpec workflow defined in [`.ai-playbook/specs/runbook-bmad-openspec.md`](.ai-playbook/specs/runbook-bmad-openspec.md) (one slice per PR, tasks tracked as PR description checklist; see [`docs/openspec-slice.md`](docs/openspec-slice.md)).
- **Direct contact**: `arturo6ramirez@gmail.com`.

## License

By contributing, you agree that your contributions will be licensed under the same terms as the project (Apache-2.0 + Commons Clause; see [LICENSE](LICENSE)).

## Development

1. Read [docs/getting-started.md](docs/getting-started.md) for prereqs + bootstrap.
2. Create a slice branch: `git checkout -b slice/<change-id>` (NOT one branch per task).
3. Run `make bootstrap` to install deps + activate pre-commit.
4. Open one PR per slice when CI is green; reviewer approves at Gate F.
