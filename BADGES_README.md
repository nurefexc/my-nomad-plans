# Nomad Travels - Achievement System

This document summarizes the achievements (badges) available in the application and the requirements to earn them.

## Available Achievements

| Icon | Name | Requirement | Description |
| :--- | :--- | :--- | :--- |
| 🛫 | **Early Bird** | Record at least 1 trip | Congratulations on creating your first travel plan! |
| 🎒 | **First Steps** | At least 1 visited country | The ice is broken, the exploration of the world has begun! |
| 🌍 | **World Explorer** | At least 10 visited countries | You are already considered a seasoned traveler in the world. |
| 🇪🇺 | **Euro-Traveler** | At least 5 visited EU countries | The gates of Europe are open before you. |
| 👑 | **EU Master** | Visit all EU countries | You are the uncrowned king of the European Union! |

## How it works?

- **Interaction-based:** Badges are automatically awarded when you add a new trip or set a trip to "visited" status.
- **Automatic evaluation:** When the Dashboard (Profile) page is opened, the system re-checks the conditions.
- **Dynamic EU list:** The list of European Union member states is requested directly from the official EU SPARQL endpoint (publications.europa.eu), so it is always up to date.
- **Database-based:** Badges are stored in the database, so they remain permanently on your profile.

## Source of EU Member States

The system uses the following SPARQL query to determine EU countries:
`https://publications.europa.eu/webapi/rdf/sparql`
