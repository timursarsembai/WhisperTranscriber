from PIL import Image, ImageDraw, ImageFont
import os

def create_splash():
    # Create a 600x400 image with a dark blue/black background
    width, height = 600, 400
    background_color = (20, 30, 40)
    image = Image.new('RGB', (width, height), background_color)
    draw = ImageDraw.Draw(image)

    # Try to use a system font, otherwise use default
    try:
        # On Windows, Segoe UI is common
        font_title = ImageFont.truetype("segoeui.ttf", 40)
        font_subtitle = ImageFont.truetype("segoeui.ttf", 20)
    except:
        font_title = ImageFont.load_default()
        font_subtitle = ImageFont.load_default()

    # Draw some waveform-like lines
    for i in range(0, width, 10):
        h = 20 + (i % 50)
        draw.line([(i, height//2 - h), (i, height//2 + h)], fill=(0, 120, 255), width=2)

    # Draw text
    title = "Whisper Transcriber"
    subtitle = "Initializing application..."
    
    # Calculate text positions (approximate centering)
    draw.text((width//2, height//2 + 80), title, fill=(255, 255, 255), anchor="mm", font=font_title)
    draw.text((width//2, height//2 + 130), subtitle, fill=(200, 200, 200), anchor="mm", font=font_subtitle)

    image.save('splash.png')
    print("Splash image created as splash.png")

if __name__ == "__main__":
    create_splash()
