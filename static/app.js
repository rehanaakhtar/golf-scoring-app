const state = {
  data: null,
  activeTab: "setup",
};

const playerRows = document.getElementById("player-rows");
const playerRowTemplate = document.getElementById("player-row-template");
const saveMessage = document.getElementById("save-message");
const scoringMessage = document.getElementById("scoring-message");
const flightSelect = document.getElementById("flight-select");
const flightSummary = document.getElementById("flight-summary");
const scorecardWrap = document.getElementById("scorecard-wrap");
const leaderboardBody = document.getElementById("leaderboard-body");
const updatedAt = document.getElementById("updated-at");
const playerCount = document.getElementById("player-count");
const flightCount = document.getElementById("flight-count");
const holesCount = document.getElementById("holes-count");
const courseBody = document.getElementById("course-body");

function playerTemplateRow(player = { name: "", handicap: 0, flight_id: "" }) {
  const fragment = playerRowTemplate.content.cloneNode(true);
  const row = fragment.querySelector("tr");
  row.querySelector(".player-name").value = player.name || "";
  row.querySelector(".player-handicap").value = Number.isInteger(player.handicap)
    ? player.handicap
    : 0;
  row.querySelector(".player-flight").value = player.flight_id || "";
  row.querySelector(".remove-player").addEventListener("click", () => row.remove());
  return fragment;
}

function addPlayerRow(player) {
  if (playerRows.children.length >= 20) {
    flash("A maximum of 20 players is supported.");
    return;
  }
  playerRows.appendChild(playerTemplateRow(player));
}

function collectPlayers() {
  return Array.from(playerRows.querySelectorAll("tr")).map((row) => ({
    name: row.querySelector(".player-name").value.trim(),
    handicap: Number(row.querySelector(".player-handicap").value || 0),
    flight_id: row.querySelector(".player-flight").value.trim().toUpperCase(),
  }));
}

function flash(message, isError = true, target = saveMessage) {
  target.textContent = message;
  target.style.color = isError ? "#9b2c2c" : "#1f6b47";
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

async function saveSetup() {
  try {
    const payload = await request("/api/setup", {
      method: "POST",
      body: JSON.stringify({ players: collectPlayers() }),
    });
    state.data = payload;
    render();
    flash("Tournament setup saved.", false, saveMessage);
    flash("Choose a flight to start scoring.", false, scoringMessage);
  } catch (error) {
    flash(error.message, true, saveMessage);
  }
}

function populateSetup(data) {
  playerRows.innerHTML = "";
  if (!data.players.length) {
    for (let i = 0; i < 4; i += 1) addPlayerRow();
    return;
  }
  data.players.forEach((player) => addPlayerRow(player));
}

function renderTabs() {
  document.querySelectorAll(".tab").forEach((button) => {
    button.classList.toggle("active", button.dataset.tab === state.activeTab);
  });
  document.querySelectorAll(".tab-panel").forEach((panel) => {
    panel.classList.toggle("active", panel.id === `tab-${state.activeTab}`);
  });
}

function renderFlightControls(data) {
  const selectedFlight = flightSelect.value;
  flightSelect.innerHTML = "";

  data.flights.forEach((flight) => {
    const option = document.createElement("option");
    option.value = flight.flight_id;
    option.textContent = `Flight ${flight.flight_id}`;
    flightSelect.appendChild(option);
  });

  if (data.flights.some((flight) => flight.flight_id === selectedFlight)) {
    flightSelect.value = selectedFlight;
  }
}

function getSelectedFlight() {
  return state.data?.flights.find((item) => item.flight_id === flightSelect.value);
}

function renderScorecard(data) {
  const flight = getSelectedFlight();
  if (!flight) {
    scorecardWrap.className = "table-wrap scorecard-wrap empty";
    scorecardWrap.innerHTML = "Save the setup above to begin score entry.";
    flightSummary.textContent = "";
    return;
  }

  flightSummary.textContent = `${flight.players.length} player(s) in flight ${flight.flight_id}`;
  const playerHeaders = flight.players
    .map(
      (player) => `
        <th>
          <div class="score-player-head">${player.name}</div>
          <div class="micro">HCP ${player.handicap}</div>
        </th>
      `,
    )
    .join("");

  const rows = data.course.holes
    .map((hole) => {
      const cells = flight.players
        .map((player) => {
          const holeScore = player.hole_scores.find((item) => item.hole === hole.number);
          return `
            <td>
              <input
                class="score-input"
                type="number"
                min="1"
                max="20"
                inputmode="numeric"
                data-player-id="${player.player_id}"
                data-hole="${hole.number}"
                value="${holeScore.gross ?? ""}"
              />
              <div class="cell-meta">
                <span>N ${holeScore.net ?? "-"}</span>
                <span>S ${holeScore.stableford ?? "-"}</span>
              </div>
            </td>
          `;
        })
        .join("");

      return `
        <tr>
          <td class="sticky-meta">
            <strong>H${hole.number}</strong>
            <div class="hole-meta-row">
              <span>P${hole.par}</span>
              <span>SI${hole.index}</span>
            </div>
          </td>
          ${cells}
        </tr>
      `;
    })
    .join("");

  scorecardWrap.className = "table-wrap scorecard-wrap";
  scorecardWrap.innerHTML = `
    <table class="scorecard-table">
      <thead>
        <tr>
          <th class="hole-head">Hole</th>
          ${playerHeaders}
        </tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>
  `;
}

function buildScorecardPayload() {
  const inputs = Array.from(scorecardWrap.querySelectorAll(".score-input"));
  const scorecard = {};

  inputs.forEach((input) => {
    const hole = input.dataset.hole;
    if (!scorecard[hole]) scorecard[hole] = [];
    scorecard[hole].push({
      player_id: input.dataset.playerId,
      gross: input.value === "" ? "" : Number(input.value),
    });
  });

  return scorecard;
}

async function saveScorecard() {
  if (!flightSelect.value) return;
  try {
    const payload = await request("/api/flight-scores", {
      method: "POST",
      body: JSON.stringify({
        flight_id: flightSelect.value,
        scorecard: buildScorecardPayload(),
      }),
    });
    state.data = payload;
    render();
    flash(`Saved scorecard for flight ${flightSelect.value}.`, false, scoringMessage);
  } catch (error) {
    flash(error.message, true, scoringMessage);
  }
}

async function clearFlightScores() {
  const flight = getSelectedFlight();
  if (!flight) return;

  const scorecard = {};
  state.data.course.holes.forEach((hole) => {
    scorecard[String(hole.number)] = flight.players.map((player) => ({
      player_id: player.player_id,
      gross: "",
    }));
  });

  try {
    const payload = await request("/api/flight-scores", {
      method: "POST",
      body: JSON.stringify({
        flight_id: flight.flight_id,
        scorecard,
      }),
    });
    state.data = payload;
    render();
    flash(`Cleared all scores for flight ${flight.flight_id}.`, false, scoringMessage);
  } catch (error) {
    flash(error.message, true, scoringMessage);
  }
}

function renderLeaderboard(data) {
  leaderboardBody.innerHTML = "";
  if (!data.leaderboard.length) {
    leaderboardBody.innerHTML =
      '<tr><td colspan="8" class="hint">Add players to see the leaderboard.</td></tr>';
    return;
  }

  data.leaderboard.forEach((player, index) => {
    const row = document.createElement("tr");
    row.innerHTML = `
      <td class="pos">${index + 1}</td>
      <td>${player.name}</td>
      <td>${player.flight_id}</td>
      <td>${player.handicap}</td>
      <td>${player.holes_played}</td>
      <td>${player.holes_played ? player.gross_total : "-"}</td>
      <td>${player.holes_played ? player.net_total : "-"}</td>
      <td>${player.holes_played ? player.stableford_total : 0}</td>
    `;
    leaderboardBody.appendChild(row);
  });
}

function renderCourse(data) {
  courseBody.innerHTML = data.course.holes
    .map(
      (hole) => `
        <tr>
          <td>${hole.number}</td>
          <td>${hole.par}</td>
          <td>${hole.index}</td>
        </tr>
      `,
    )
    .join("");
}

function renderSummary(data) {
  playerCount.textContent = data.players.length;
  flightCount.textContent = data.flights.length;
  holesCount.textContent = data.course.holes.length;
  updatedAt.textContent = data.updated_at
    ? `Updated ${new Date(data.updated_at * 1000).toLocaleString()}`
    : "Waiting for scores...";
}

function render() {
  if (!state.data) return;
  renderTabs();
  populateSetup(state.data);
  renderFlightControls(state.data);
  renderScorecard(state.data);
  renderLeaderboard(state.data);
  renderCourse(state.data);
  renderSummary(state.data);
}

async function boot() {
  try {
    state.data = await request("/api/state");
    render();
  } catch (error) {
    flash(error.message, true, saveMessage);
  }

  const events = new EventSource("/api/events");
  events.onmessage = (event) => {
    state.data = JSON.parse(event.data);
    render();
  };
  events.onerror = () => {
    updatedAt.textContent = "Live connection interrupted. Refresh to reconnect.";
  };
}

document.querySelectorAll(".tab").forEach((button) => {
  button.addEventListener("click", () => {
    state.activeTab = button.dataset.tab;
    renderTabs();
  });
});

document.getElementById("add-player").addEventListener("click", () => addPlayerRow());
document.getElementById("save-setup").addEventListener("click", saveSetup);
document.getElementById("save-scorecard").addEventListener("click", saveScorecard);
document.getElementById("clear-flight").addEventListener("click", clearFlightScores);
flightSelect.addEventListener("change", () => renderScorecard(state.data));

boot();
