# Themes & characters {#themes-characters}

## Make text comfortable {#make-text-comfortable}

**Settings → Appearance** switches between Simplified Chinese and English and scales text from 50% to 200%. Preferences save immediately. Conversation contents, project names and custom provider data keep their original language.

[![Language and text-size settings](/images/appearance-en.png)](/images/appearance-en.png)

## Choose colors and characters separately {#choose-colors-and-characters-separately}

Themes control colors. The main character supplies welcome art, avatars, reply interactions, loading and file-catching art. Changing a theme preserves your chosen character and does not change the agent's identity or capabilities.

Sea-salt blue is a color theme; its preview is not tied to Yanami. Open **Appearance → Themes → Main character** to select a built-in or import a character ZIP. Complete built-in main characters include Yanami, Komari, Kaju Nukumizu, Tiara Basori and Whale Girl. They cannot be deleted or overwritten.

You can assign the four ordinary subagent appearance slots separately. Global agents choose a character during creation or editing; Kazuhiko Nukumizu is available as a subagent character. Desktop pets have independent appearance settings.

[![Theme cards and the Main character entry](/images/themes-en.png)](/images/themes-en.png)

*Choose colors first; use Main character to change the artwork. You can download and import the [pure-white theme](/examples/pure-white.umeko-theme.json) used in these screenshots.*

[![Main character selection and ZIP import](/images/characters-en.png)](/images/characters-en.png)

*Select a built-in character, import a ZIP, or export the character-making Skill at the bottom.*

## Create and import themes {#create-and-import-themes}

Copy the creation prompt in Appearance, or ask the agent:

> Create and apply a pure-white theme with a muted green accent and readable text. Keep my current character.

Themes are color-only JSON without scripts. Importing applies a theme; the same ID updates it. Deleting the selected custom theme restores its base colors.

## Create character packs {#create-character-packs}

Export the character-making Skill from the character dialog. Give it to an agent to prepare transparent art, a manifest and optional dialogue, then package them in a ZIP. Imported assets are copied into the profile and no longer depend on the original creation directory.

Packs contain only JSON and images, with no scripts or external asset paths. See the [character asset specification](https://github.com/umeiko/umeko-desktop/blob/main/docs/characters.md) for formats and limits; this reference is currently in Chinese.
