import re, os

os.makedirs('app/static/css', exist_ok=True)

all_css = []
for name in ['landing', 'brand', 'auth', 'app', 'admin']:
    html = open(f'docs/design_unpacked/{name}.html', encoding='utf-8').read()
    styles = re.findall(r'<style[^>]*>(.*?)</style>', html, re.S)
    for i, s in enumerate(styles):
        # Skip font-face blocks (too large, we'll use Google Fonts instead)
        if '@font-face' in s and len(s) > 5000:
            # Keep only non-font-face parts
            parts = re.split(r'@font-face\s*\{', s)
            non_font = parts[0]  # everything before first @font-face
            for j in range(1, len(parts)):
                # Find the closing brace of each @font-face
                depth = 1
                k = 0
                while k < len(parts[j]) and depth > 0:
                    if parts[j][k] == '{': depth += 1
                    elif parts[j][k] == '}': depth -= 1
                    k += 1
                # Skip the font-face block
                if k < len(parts[j]):
                    non_font += parts[j][k:]
            s = non_font
        if s.strip():
            all_css.append(f'/* {name} style {i} */\n{s.strip()}')

combined = '\n\n'.join(all_css)
with open('app/static/css/theme.css', 'w', encoding='utf-8') as f:
    f.write(combined)

print(f'Combined CSS: {len(combined)} chars')
print('Saved to app/static/css/theme.css')
