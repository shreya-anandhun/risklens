#!/usr/bin/env bash
# Download the four Kaggle datasets RiskLens is built on into data/kaggle.
# Public datasets download without an API key; with the Kaggle CLI configured you can use it instead:
#   kaggle datasets download -d <slug> --unzip -p data/kaggle/<name>
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p data/kaggle
for slug in \
  nudratabbas/global-supply-chain-risk-and-logistics-2024-2026 \
  princehobby/geopolitical-risk-datasets \
  shashwatwork/dataco-smart-supply-chain-for-big-data-analysis \
  ayodejiibrahimlateef/supply-chain-datasets; do
  name=$(basename "$slug")
  echo "downloading $slug"
  curl -sSL -o "data/kaggle/$name.zip" "https://www.kaggle.com/api/v1/datasets/download/$slug"
  mkdir -p "data/kaggle/$name" && unzip -o -q "data/kaggle/$name.zip" -d "data/kaggle/$name" && rm "data/kaggle/$name.zip"
done
echo "done. Rebuild with: python -m risklens.pipeline"
