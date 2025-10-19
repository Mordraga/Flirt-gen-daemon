from engine import load_spice_levels, build_prompt, ask_ollama

if __name__ == "__main__":
    spice_data = load_spice_levels()

    print("💋 Flirt Daemon Engine Test 💋\n")

    theme = input("Theme (e.g. coffee, gaming, stars): ").strip()
    style = input("Style (e.g. romantic, funny, clever): ").strip()
    try:
        level = int(input("Spice level (1–10): ").strip())
    except ValueError:
        level = 1

    prompt = build_prompt(theme, style, level, spice_data)
    print("\n🧠 Sending prompt to Ollama:")
    print(prompt)

    result = ask_ollama(prompt, model="dolphin3:8b")
    print("\n💬 Generated flirt:")
    print(result)
