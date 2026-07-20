# DISCLAIMER — Marketia OLX Poster

**Ta aplikacja automatyzuje operacje, które mogą naruszać regulamin OLX.pl oraz przepisy
prawa autorskiego/ochrony danych w niektórych jurysdykcjach. Zanim uruchomisz, przeczytaj
i zaakceptuj poniższe punkty. Pierwsze uruchomienie wymaga świadomej zgody (checkbox
in-app zablokowany do potwierdzenia).**

## 1. Automatyczne wystawianie ogłoszeń narusza OLX ToS

Regulamin OLX.pl zabrania korzystania z serwisu przy użyciu automatycznych narzędzi
(bots, scrapers, listing generators). Świadome korzystanie z tej aplikacji oznacza
akceptację ryzyka **zablokowania konta bez ostrzeżenia oraz utraty aktywnych aukcji
i historii transakcji**. Marketia nie ponosi odpowiedzialności za konsekwencje.

## 2. Multi-accounting (3 konta jednego użytkownika) narusza regulamin

Regulamin OLX zabrania prowadzenia więcej niż jednego konta prywatnego. Aplikacja
zakłada 3 konta (marketia-glowne, marketia-warszawa, marketia-krakow) i traktuje je
jako oddzielne tożsamości. Jest to świadome naruszenie regulaminu. **Ryzyko permanent
ban wszystkich powiązanych kont — pełną odpowiedzialność ponosi użytkownik.**

## 3. `playwright-stealth` = evasion detection

Biblioteka `playwright-stealth` maskuje sygnały automatyzacji przeglądarki
(navigator.webdriver, plugins fingerprint, WebGL renderer). W niektórych jurysdykcjach
(m.in. USA — CFAA) może być interpretowana jako "circumventing technical measures"
lub "unauthorized access". **Zalecana konsultacja prawna przed użyciem produkcyjnym.**
Niniejszy tekst nie jest poradą prawną.

## 4. Multi-city variants mogą stanowić spam / wprowadzać w błąd

Aplikacja generuje 3–6 wariantów opisu tego samego produktu, każdy przypisany do
innego miasta. Warunek etyczny: **lokalizacje muszą odpowiadać rzeczywistym punktom
wysyłki lub dostępności produktu**. Wystawianie fake lokacji ("Kraków" gdy magazyn
jest w Warszawie bez wysyłki do Krakowa) narusza ustawę o zwalczaniu nieuczciwej
konkurencji i regulamin OLX (art. 5 lit. b).

## 5. Humanizer + fingerprint spoofing = pogranicze "circumventing technical measures"

Random delays 90–240s, human-like typing z typos, mouse jitter, plugins spoofing,
timezone/locale forcing — wszystko to celowo obchodzi mechanizmy anti-bot OLX.
Aplikacja stosuje kill-switch, hard daily cap (25/dzień/konto) i warmup 7 dni dla
nowych kont, ale ryzyko interpretacji prawnej pozostaje po stronie użytkownika.

## 6. CAPTCHA — wyłącznie manual solve

Aplikacja **NIE integruje** się z 2captcha, anti-captcha ani żadnym zewnętrznym
serwisem rozwiązywania CAPTCHA — auto-solving narusza reCAPTCHA ToS. Gdy OLX
pokaże CAPTCHA, aplikacja pauzuje konto i wyświetla modal "rozwiąż ręcznie". Nie
próbuj obchodzić tego trybu.

## 7. PII w screenshotach — retencja 30 dni, brak backupu w chmurze bez szyfrowania

Screenshoty potwierdzenia (`output/screenshots/`) zawierają dane osobowe (numer
telefonu, adres wysyłki, imię/nazwisko z konta OLX). Aplikacja automatycznie
usuwa screenshoty starsze niż 30 dni. Katalog `output/` jest w `.gitignore`.
**Nie backup'uj `output/` do iCloud/Dropbox bez szyfrowania end-to-end.**

---

## Akceptacja

Uruchomienie aplikacji po raz pierwszy zapisze w `data/consent.json` timestamp
akceptacji powyższych 7 punktów. Bez tego zapisu aplikacja się nie uruchomi.

Data ostatniej aktualizacji: 2026-07-17.
