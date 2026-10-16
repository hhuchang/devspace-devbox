"""Run Full Validation's lifecycle scenarios without the data-plane tour."""

from validate_full import main

if __name__ == "__main__":
    main(lifecycle_only=True)
