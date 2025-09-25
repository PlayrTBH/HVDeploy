<?php
session_start();

if (!isset($_SESSION['user'])) {
    header('Location: index.php');
    exit;
}

$config = require __DIR__ . '/../config.php';
$dataFile = $config['data_file'];

if (!file_exists($dataFile)) {
    file_put_contents($dataFile, json_encode([]), LOCK_EX);
}

$links = json_decode(file_get_contents($dataFile), true);
if (!is_array($links)) {
    $links = [];
}

$errors = $_SESSION['flash_errors'] ?? [];
$success = $_SESSION['flash_success'] ?? null;
unset($_SESSION['flash_errors'], $_SESSION['flash_success']);

if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    $action = $_POST['action'] ?? '';
    $errors = [];
    $success = null;

    if ($action === 'add') {
        $label = trim($_POST['label'] ?? '');
        $url = trim($_POST['url'] ?? '');

        if ($label === '') {
            $errors[] = 'A label is required.';
        }

        if ($url === '' || !filter_var($url, FILTER_VALIDATE_URL)) {
            $errors[] = 'A valid URL is required.';
        }

        if (!$errors) {
            $links[] = [
                'label' => $label,
                'url' => $url,
            ];

            file_put_contents($dataFile, json_encode($links, JSON_PRETTY_PRINT), LOCK_EX);
            $success = 'Link added successfully.';
        }
    } elseif ($action === 'delete') {
        $index = filter_input(INPUT_POST, 'index', FILTER_VALIDATE_INT);
        if ($index === null || $index === false || !isset($links[$index])) {
            $errors[] = 'Invalid link selection.';
        } else {
            array_splice($links, $index, 1);
            $links = array_values($links);
            file_put_contents($dataFile, json_encode($links, JSON_PRETTY_PRINT), LOCK_EX);
            $success = 'Link removed successfully.';
        }
    } else {
        $errors[] = 'Unknown action.';
    }

    if ($errors) {
        $_SESSION['flash_errors'] = $errors;
    }

    if ($success) {
        $_SESSION['flash_success'] = $success;
    }

    header('Location: dashboard.php');
    exit;
}
?>
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta http-equiv="X-UA-Compatible" content="IE=edge">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Service Hub Dashboard</title>
    <link rel="stylesheet" href="assets/styles.css">
</head>
<body>
    <div class="container">
        <header class="header">
            <h1>Service Hub</h1>
            <div>
                <span class="welcome">Signed in as <?php echo htmlspecialchars($_SESSION['user'], ENT_QUOTES, 'UTF-8'); ?></span>
                <a class="button" href="logout.php">Log out</a>
            </div>
        </header>

        <?php if ($success): ?>
            <div class="alert success"><?php echo htmlspecialchars($success, ENT_QUOTES, 'UTF-8'); ?></div>
        <?php endif; ?>

        <?php if ($errors): ?>
            <div class="alert error">
                <ul>
                    <?php foreach ($errors as $error): ?>
                        <li><?php echo htmlspecialchars($error, ENT_QUOTES, 'UTF-8'); ?></li>
                    <?php endforeach; ?>
                </ul>
            </div>
        <?php endif; ?>

        <section class="card">
            <h2>Add a service link</h2>
            <form method="post" class="form-grid">
                <input type="hidden" name="action" value="add">
                <label>
                    Label
                    <input type="text" name="label" required>
                </label>
                <label>
                    URL
                    <input type="url" name="url" placeholder="https://example.com" required>
                </label>
                <button type="submit" class="button primary">Add link</button>
            </form>
        </section>

        <section class="card">
            <h2>Available services</h2>
            <?php if (!$links): ?>
                <p>No links have been added yet.</p>
            <?php else: ?>
                <ul class="link-list">
                    <?php foreach ($links as $index => $link): ?>
                        <li>
                            <span>
                                <strong><?php echo htmlspecialchars($link['label'], ENT_QUOTES, 'UTF-8'); ?></strong>
                                <a href="<?php echo htmlspecialchars($link['url'], ENT_QUOTES, 'UTF-8'); ?>" target="_blank" rel="noopener noreferrer">
                                    <?php echo htmlspecialchars($link['url'], ENT_QUOTES, 'UTF-8'); ?>
                                </a>
                            </span>
                            <form method="post" class="inline-form" onsubmit="return confirm('Remove this link?');">
                                <input type="hidden" name="action" value="delete">
                                <input type="hidden" name="index" value="<?php echo $index; ?>">
                                <button type="submit" class="button danger">Remove</button>
                            </form>
                        </li>
                    <?php endforeach; ?>
                </ul>
            <?php endif; ?>
        </section>
    </div>
</body>
</html>
