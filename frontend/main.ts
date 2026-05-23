import { install as installEntries } from "./entries";
import { install as installFolders } from "./folders";
import { install as installHelpDialog } from "./help-dialog";
import { install as installLocaltime } from "./localtime";
import { install as installShortcuts } from "./shortcuts";

installFolders();
installEntries();
installHelpDialog();
installShortcuts();
installLocaltime();
