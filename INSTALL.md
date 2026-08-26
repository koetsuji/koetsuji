# GitHub profile README — designer v2

This version intentionally avoids the common "AI portfolio" look:
- no glassmorphism
- no big rainbow gradients
- no emoji icons
- no badge wall
- no fake terminal overload
- restrained color, spacing and typography
- dark-mode aware
- subtle SVG-only motion

## Install

Create/use the public profile repository:

`koetsuji/koetsuji`

Put these files at its root:

- `README.md`
- `assets/hero.svg`
- `assets/repo-01.svg`
- `assets/repo-02.svg`
- `assets/repo-03.svg`

GitHub profile READMEs do not allow arbitrary custom CSS/JavaScript.
The styling and motion live inside the SVG assets instead.

## Animation

The motion is deliberately tiny:
- status dot slowly breathes
- cursor softly blinks
- each repo card has a very slow activity dot

There is no JavaScript.

## Typography

The primary type stack is:

`ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, Liberation Mono, monospace`

This gives a coder feel without turning the page into a fake terminal.
