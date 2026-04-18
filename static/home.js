const nameInput = document.getElementById("tournament-create-name");
const createButton = document.getElementById("create-tournament");
const createMessage = document.getElementById("create-message");
const shareResult = document.getElementById("share-result");
const shareUrl = document.getElementById("share-url");
const copyShareUrl = document.getElementById("copy-share-url");
const openTournament = document.getElementById("open-tournament");
const recentTournaments = document.getElementById("recent-tournaments");

function flashHome(message, isError = false) {
  createMessage.textContent = message;
  createMessage.style.color = isError ? "#9b2c2c" : "#1f6b47";
}

async function request(url, options = {}) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.error || "Request failed.");
  }
  return payload;
}

function renderRecent(tournaments) {
  if (!tournaments.length) {
    recentTournaments.innerHTML =
      '<p class="hint">No tournaments yet. Create the first one above.</p>';
    return;
  }

  recentTournaments.innerHTML = tournaments
    .map(
      (tournament) => `
        <a class="recent-card" href="/t/${tournament.id}">
          <strong>${tournament.name || "Untitled Tournament"}</strong>
          <span>${tournament.player_count} players • ${tournament.status}</span>
        </a>
      `,
    )
    .join("");
}

async function loadRecent() {
  try {
    const payload = await request("/api/tournaments");
    renderRecent(payload.tournaments || []);
  } catch (error) {
    recentTournaments.innerHTML = `<p class="hint">${error.message}</p>`;
  }
}

async function createTournament() {
  try {
    const payload = await request("/api/tournaments", {
      method: "POST",
      body: JSON.stringify({ name: nameInput.value.trim() }),
    });
    shareResult.classList.remove("hidden");
    shareUrl.value = payload.share_url;
    openTournament.href = payload.share_url;
    flashHome("Tournament created. Share the link below.", false);
    await loadRecent();
  } catch (error) {
    flashHome(error.message, true);
  }
}

createButton.addEventListener("click", createTournament);
copyShareUrl.addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(shareUrl.value);
    flashHome("Tournament link copied.", false);
  } catch {
    flashHome("Copy failed. You can copy the URL manually.", true);
  }
});

loadRecent();
