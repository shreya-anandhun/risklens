"""Rebuild everything from the Kaggle downloads: processed tables, the model, the consignment book."""
from . import book, datasets, train
from .predictor import load_model


def main():
    datasets.build()
    print("built data/processed from data/kaggle")
    train.main()
    load_model.cache_clear()
    model, _ = load_model()
    b = book.build(model)
    print(f"wrote {book.BOOK_PATH.name}: {len(b)} consignments")


if __name__ == "__main__":
    main()
