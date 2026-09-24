"""Run Phases 1-3 end to end: data → features → model."""
from . import generate_data, features, train

if __name__ == "__main__":
    generate_data.main()
    features.main()
    train.main()
