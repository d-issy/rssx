import { install as installAddFeedDialog } from "./add-feed-dialog";
import { install as installEntries } from "./entries";
import { install as installFolders } from "./folders";
import { install as installHelpDialog } from "./help-dialog";
import { install as installLocaltime } from "./localtime";
import { install as installManageDialog } from "./manage-dialog";
import { install as installRelativeTime } from "./relative-time";
import { install as installShortcuts } from "./shortcuts";
import { install as installToast } from "./toast";

installFolders();
installEntries();
installHelpDialog();
installManageDialog();
installAddFeedDialog();
installToast();
installRelativeTime();
installShortcuts();
installLocaltime();
