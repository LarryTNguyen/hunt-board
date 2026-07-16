# Route map

## Existing API routes

The FastAPI entry point is `src/hunt_board/main.py`. Its routes are backend JSON APIs and are not part of the landing-page design.

## Frontend routes

- `/`: standalone static landing page at `mock-designs/index.html`.

Product mockups are cross-linked static pages in `mock-designs/` and share `app.css` and `app.js`.

The page is not mounted in FastAPI and makes no API requests.
