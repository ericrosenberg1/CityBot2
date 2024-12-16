def test_imports():
    try:
        from atproto import Client
        print("atproto import successful")
    except Exception as e:
        print(f"atproto import failed: {e}")

    try:
        from multiformats import CID
        print("multiformats import successful")
    except Exception as e:
        print(f"multiformats import failed: {e}")

    try:
        import dag_cbor
        print("dag-cbor import successful")
    except Exception as e:
        print(f"dag-cbor import failed: {e}")

if __name__ == "__main__":
    test_imports()