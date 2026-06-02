#!/bin/bash
# Скрипт для першого завантаження на GitHub
# Використання: bash init_github.sh YOUR_GITHUB_USERNAME

set -e

USERNAME=${1:-"YOUR_USERNAME"}
REPO="cosmo-schedule"

echo "=> Ініціалізація git..."
git init
git add .
git commit -m "init: однофайловий прототип розкладу косметологічного кабінету"

echo ""
echo "=> Далі виконай вручну (потрібен токен або SSH):"
echo ""
echo "   # Якщо SSH:"
echo "   git remote add origin git@github.com:${USERNAME}/${REPO}.git"
echo ""
echo "   # Якщо HTTPS:"
echo "   git remote add origin https://github.com/${USERNAME}/${REPO}.git"
echo ""
echo "   git branch -M main"
echo "   git push -u origin main"
echo ""
echo "   Репозиторій створи на: https://github.com/new"
echo "   Назва: ${REPO} | Без README (ми вже маємо свій)"
