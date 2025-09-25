<?php
session_start();

if (isset($_SESSION['user'])) {
    header('Location: dashboard.php');
    exit;
}

$config = require __DIR__ . '/../config.php';
$users = $config['users'];

$error = null;

if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    $username = trim($_POST['username'] ?? '');
    $password = $_POST['password'] ?? '';

    if (isset($users[$username]) && password_verify($password, $users[$username])) {
        $_SESSION['user'] = $username;
        header('Location: dashboard.php');
        exit;
    }

    $error = 'Invalid username or password.';
}
?>
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta http-equiv="X-UA-Compatible" content="IE=edge">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Service Hub Login</title>
    <link rel="stylesheet" href="assets/styles.css">
</head>
<body>
    <div class="login-container">
        <form method="post" class="login-card">
            <h1>Service Hub</h1>
            <p class="subtitle">Sign in to manage your internal services.</p>

            <?php if ($error): ?>
                <div class="alert error"><?php echo htmlspecialchars($error, ENT_QUOTES, 'UTF-8'); ?></div>
            <?php endif; ?>

            <label>
                Username
                <input type="text" name="username" required autofocus>
            </label>

            <label>
                Password
                <input type="password" name="password" required>
            </label>

            <button type="submit" class="button primary full-width">Sign in</button>
        </form>
    </div>
</body>
</html>
