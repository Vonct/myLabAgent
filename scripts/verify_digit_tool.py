from digit_infer_service import recognize_handwritten_digit


def main():
    result = recognize_handwritten_digit(
        "tools_needed_to_intergrate/number_detection/samples/digits/digit_3_1.png"
    )
    print(result["digit"])
    print(round(result["confidence"], 6))


if __name__ == "__main__":
    main()
