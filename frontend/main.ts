import { install as installAddFeedDialog } from "./features/dialogs/add-feed";
import { install as installHelpDialog } from "./features/dialogs/help";
import { install as installManageDialog } from "./features/dialogs/manage";
import { install as installEntries } from "./features/entries";
import { install as installShortcuts } from "./features/shortcuts";
import { install as installFolders } from "./features/sidebar/folders";
import { install as installLocaltime } from "./lib/localtime";
import { install as installRelativeTime } from "./lib/relative-time";
import { install as installToast } from "./lib/toast";

installFolders();
installEntries();
installHelpDialog();
installManageDialog();
installAddFeedDialog();
installToast();
installRelativeTime();
installShortcuts();
installLocaltime();
