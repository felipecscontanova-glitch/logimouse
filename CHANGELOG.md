# Histórico de versões

## 1.1.0 (2026-11-04)

- Ícone na barra com a % da bateria e aviso de bateria baixa.
- Ajustes salvos por mouse em `~/.config/logimouse/config.json`.
- Reaplica os ajustes ao iniciar e quando o mouse reconecta (desligar/ligar, receptor recolocado,
  Bluetooth reconectado).
- Opção de iniciar com o sistema, pelo painel, pelo ícone ou por `logimouse --autostart on`.
- Novo cartão "Aplicativo" no painel e botão "Esquecer ajustes".
- Novos comandos: `--tray`, `--reapply`, `--autostart`.
- Instalador instala as dependências sozinho (apt, dnf, pacman, zypper) e tem `--remover`.
- Código separado em módulos, com testes automáticos e CI.

## 1.0.0 (2026-11-04)

- Primeira versão: painel com bateria, DPI, velocidade do ponteiro, taxa de atualização,
  roda (catraca/livre, SmartShift, alta resolução, inverter) e modo host.
- Modo terminal (`--cli`, `--dpi`) e mouse simulado (`--demo`).
