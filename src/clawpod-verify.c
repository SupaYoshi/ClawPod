#include <gpod/itdb.h>
#include <glib.h>
#include <stdio.h>

int main(int argc, char **argv) {
    if (argc != 2) {
        fprintf(stderr, "usage: %s MOUNTPOINT\n", argv[0]);
        return 2;
    }
    GError *error = NULL;
    Itdb_iTunesDB *db = itdb_parse(argv[1], &error);
    if (!db) {
        fprintf(stderr, "database parse failed: %s\n",
                error && error->message ? error->message : "unknown error");
        if (error) g_error_free(error);
        return 1;
    }

    unsigned tracks = 0, missing = 0;
    for (GList *node = db->tracks; node; node = node->next) {
        Itdb_Track *track = node->data;
        char *filename = itdb_filename_on_ipod(track);
        tracks++;
        if (!filename || !g_file_test(filename, G_FILE_TEST_IS_REGULAR)) {
            fprintf(stderr, "MISSING\t%s\t%s\t%s\n",
                    track->artist ? track->artist : "",
                    track->title ? track->title : "",
                    filename ? filename : "");
            missing++;
        }
        g_free(filename);
    }
    Itdb_Playlist *master = itdb_playlist_mpl(db);
    unsigned master_tracks = master ? g_list_length(master->members) : 0;
    printf("VERIFY\ttracks=%u\tmaster_tracks=%u\tmissing_files=%u\n",
           tracks, master_tracks, missing);
    itdb_free(db);
    return missing == 0 && tracks == master_tracks ? 0 : 1;
}
