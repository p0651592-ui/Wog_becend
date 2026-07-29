const express = require('express');
const cors = require('cors');

const app = express();
app.use(cors());
app.use(express.json());

// Глобальная база данных игроков казино в оперативной памяти сервера
let db = {
    users: {},
    promos: {}
};

const OWNER_ID = 6682822292; // Ваш ID Администратора

// 1. АВТОРИЗАЦИЯ И РЕГИСТРАЦИЯ ИГРОКА
app.post('/api/user', (req, res) => {
    let { id, first_name, username } = req.body;
    
    if (!id || Number(id) === OWNER_ID) {
        id = OWNER_ID;
        first_name = "Основатель (WOG)";
        username = "FounderAdmin";
    }

    const assignedRole = (Number(id) === OWNER_ID) ? "admin" : "user";

    if (!db.users[id]) {
        db.users[id] = {
            id: Number(id),
            name: first_name,
            username: username,
            balance: 5000, // Стартовый капитал при первой игре
            role: assignedRole
        };
    }
    res.json(db.users[id]);
});

// 2. ДВИЖОК ИГРЫ В КОСТИ (ВСЕРАСЧЕТ НА СЕРВЕРЕ)
app.post('/api/game/dice', (req, res) => {
    const { id, bet, target } = req.body; // target: 'under' (меньше 4) или 'over' (больше 3)
    const searchId = id ? Number(id) : OWNER_ID;

    if (!db.users[searchId]) return res.status(440).get({ error: "User not found" });
    
    const player = db.users[searchId];
    if (player.balance < bet || bet <= 0) {
        return res.status(400).json({ error: "Недостаточно монет для ставки!" });
    }

    // Сервер сам бросает кость (от 1 до 6)
    const diceResult = Math.floor(Math.random() * 6) + 1;
    let isWin = false;

    if (target === 'under' && diceResult <= 3) isWin = true;
    if (target === 'over' && diceResult >= 4) isWin = true;

    // Списание или начисление баланса в базе данных сервера
    if (isWin) {
        player.balance += parseInt(bet); // Удваиваем ставку (возвращаем ставку + выигрыш)
    } else {
        player.balance -= parseInt(bet);
    }

    // Возвращаем результат фронтенду: число кубика, статус победы и защищенный баланс
    res.json({
        success: true,
        dice: diceResult,
        win: isWin,
        balance: player.balance
    });
});

// 3. ДВИЖОК КОЛЕСА ФОРТУНЫ (РАСЧЕТ НА СЕРВЕРЕ)
app.post('/api/game/wheel', (req, res) => {
    const { id, bet } = req.body;
    const searchId = id ? Number(id) : OWNER_ID;

    if (!db.users[searchId]) return res.status(440).json({ error: "User not found" });
    
    const player = db.users[searchId];
    if (player.balance < bet || bet <= 0) {
        return res.status(400).json({ error: "Недостаточно монет для ставки!" });
    }

    // Сектора колеса: множители x0, x2, x5, x0, x10, x0
    const sectors =;
    const randomIndex = Math.floor(Math.random() * sectors.length);
    const multiplier = sectors[randomIndex];

    player.balance -= parseInt(bet); // Снимаем ставку
    const winAmount = bet * multiplier;
    player.balance += winAmount; // Начисляем выигрыш с множителем

    res.json({
        success: true,
        sectorIndex: randomIndex, // Какой сектор должен визуально выпасть на фронтенде
        multiplier: multiplier,
        winAmount: winAmount,
        balance: player.balance
    });
});

// 4. СЛУЖЕБНЫЕ НАЧИСЛЕНИЯ И АДМИНКА
app.post('/api/balance', (req, res) => {
    const { id, amount } = req.body;
    const searchId = id ? Number(id) : OWNER_ID;

    if (!db.users[searchId]) {
        db.users[searchId] = {
            id: searchId,
            name: "Игрок казино",
            username: "",
            balance: 5000,
            role: "user"
        };
    }

    db.users[searchId].balance += parseInt(amount);
    if (db.users[searchId].balance < 0) db.users[searchId].balance = 0;

    res.json({ success: true, balance: db.users[searchId].balance });
});

// ПРОМОКОДЫ
app.post('/api/promo/create', (req, res) => {
    const { admin_id, code, reward, uses } = req.body;
    if (Number(admin_id) !== OWNER_ID) return res.status(403).json({ error: "Access denied" });
    const cleanCode = code.trim().toUpperCase();
    db.promos[cleanCode] = { reward: parseInt(reward), uses: parseInt(uses), claimed_by: [] };
    res.json({ success: true });
});

app.post('/api/promo/activate', (req, res) => {
    const { id, code } = req.body;
    const searchId = id ? Number(id) : OWNER_ID;
    const cleanCode = code.trim().toUpperCase();

    if (!db.users[searchId]) return res.status(404).json({ error: "User not found" });
    if (!db.promos[cleanCode]) return res.status(440).json({ error: "Promo not found" });
    if (db.promos[cleanCode].uses <= 0) return res.status(400).json({ error: "Promo expired" });
    if (db.promos[cleanCode].claimed_by.includes(searchId)) return res.status(400).json({ error: "Already claimed" });

    db.users[searchId].balance += db.promos[cleanCode].reward;
    db.promos[cleanCode].uses -= 1;
    db.promos[cleanCode].claimed_by.push(searchId);

    res.json({ success: true, balance: db.users[searchId].balance, message: `Код активирован! +${db.promos[cleanCode].reward} W` });
});

app.post('/api/promo/list', (req, res) => { res.json(db.promos); });
app.get('/', (req, res) => { res.send("WOG Casino Core Online Engine"); });

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => console.log(`Casino Engine Active`));
