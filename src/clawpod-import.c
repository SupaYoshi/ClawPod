#include <gpod/itdb.h>
#include <glib.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

static void print_error(const char *what, GError *error) {
    fprintf(stderr, "%s: %s\n", what,
            (error && error->message) ? error->message : "unknown error");
    if (error) g_error_free(error);
}

static char *fold(const char *value) {
    char *casefolded = g_utf8_casefold(value ? value : "", -1);
    char *normalized = g_utf8_normalize(casefolded, -1, G_NORMALIZE_ALL_COMPOSE);
    g_free(casefolded);
    g_strstrip(normalized);
    return normalized;
}

static gboolean same_text(const char *a, const char *b) {
    char *fa = fold(a);
    char *fb = fold(b);
    gboolean same = g_strcmp0(fa, fb) == 0;
    g_free(fa);
    g_free(fb);
    return same;
}

static Itdb_Track *find_duplicate(Itdb_iTunesDB *db, const char *title,
                                  const char *artist, const char *album) {
    (void)album;
    for (GList *node = db->tracks; node; node = node->next) {
        Itdb_Track *track = node->data;
        if (same_text(track->title, title) &&
            same_text(track->artist, artist)) {
            return track;
        }
    }
    return NULL;
}

static unsigned parse_uint(const char *value) {
    char *end = NULL;
    unsigned long parsed = strtoul(value ? value : "", &end, 10);
    return end == value ? 0 : (unsigned)parsed;
}

static void usage(const char *program) {
    fprintf(stderr, "usage: %s MOUNTPOINT MANIFEST.tsv\n", program);
    fprintf(stderr, "fields: source, title, artist, album, genre, year, "
                    "duration_ms, track_nr, track_count, bitrate_kbps, samplerate\n");
}

int main(int argc, char **argv) {
    if (argc != 3) {
        usage(argv[0]);
        return 2;
    }

    GError *error = NULL;
    Itdb_iTunesDB *db = itdb_parse(argv[1], &error);
    if (!db) {
        print_error("database parse failed", error);
        return 1;
    }
    Itdb_Playlist *master = itdb_playlist_mpl(db);
    if (!master) {
        fprintf(stderr, "master playlist not found\n");
        itdb_free(db);
        return 1;
    }

    gchar *contents = NULL;
    gsize length = 0;
    if (!g_file_get_contents(argv[2], &contents, &length, &error)) {
        print_error("manifest read failed", error);
        itdb_free(db);
        return 1;
    }

    unsigned added = 0, skipped = 0, removed = 0, failed = 0, line_number = 0;

    /* Clean repeated sync/test entries before processing the manifest. */
    GHashTable *seen = g_hash_table_new_full(g_str_hash, g_str_equal, g_free, NULL);
    GPtrArray *duplicate_files = g_ptr_array_new_with_free_func(g_free);
    for (GList *node = db->tracks; node;) {
        GList *next = node->next;
        Itdb_Track *track = node->data;
        char *artist = fold(track->artist);
        char *title = fold(track->title);
        char *key = g_strconcat(artist, "\x1f", title, NULL);
        g_free(artist);
        g_free(title);
        if (g_hash_table_contains(seen, key)) {
            char *filename = itdb_filename_on_ipod(track);
            printf("REMOVE_DUPLICATE\t%s\t%s\n",
                   track->artist ? track->artist : "", track->title ? track->title : "");
            for (GList *playlist_node = db->playlists; playlist_node;
                 playlist_node = playlist_node->next) {
                Itdb_Playlist *playlist = playlist_node->data;
                while (g_list_find(playlist->members, track)) {
                    itdb_playlist_remove_track(playlist, track);
                }
            }
            itdb_track_remove(track);
            if (filename) g_ptr_array_add(duplicate_files, filename);
            g_free(key);
            removed++;
        } else {
            g_hash_table_add(seen, key);
        }
        node = next;
    }
    g_hash_table_destroy(seen);

    gchar **lines = g_strsplit(contents, "\n", -1);
    for (gchar **line = lines; *line; line++) {
        line_number++;
        if (!**line || **line == '#') continue;

        gchar **field = g_strsplit(*line, "\t", 11);
        if (g_strv_length(field) != 11) {
            fprintf(stderr, "line %u: expected 11 tab-separated fields\n", line_number);
            failed++;
            g_strfreev(field);
            continue;
        }

        struct stat st;
        if (stat(field[0], &st) != 0) {
            fprintf(stderr, "line %u: source is unreadable: %s\n", line_number, field[0]);
            failed++;
            g_strfreev(field);
            continue;
        }
        if (find_duplicate(db, field[1], field[2], field[3])) {
            printf("SKIP\t%s\t%s\n", field[2], field[1]);
            skipped++;
            g_strfreev(field);
            continue;
        }

        Itdb_Track *track = itdb_track_new();
        track->title = g_strdup(field[1]);
        track->artist = g_strdup(field[2]);
        track->albumartist = g_strdup(field[2]);
        track->album = g_strdup(field[3]);
        track->genre = g_strdup(field[4]);
        track->filetype = g_strdup("MPEG audio file");
        track->year = parse_uint(field[5]);
        track->tracklen = parse_uint(field[6]);
        track->track_nr = parse_uint(field[7]);
        track->tracks = parse_uint(field[8]);
        track->bitrate = parse_uint(field[9]);
        track->samplerate = parse_uint(field[10]);
        track->samplerate2 = (float)track->samplerate;
        track->size = (guint32)st.st_size;
        track->time_added = time(NULL);
        track->time_modified = st.st_mtime;
        track->mediatype = ITDB_MEDIATYPE_AUDIO;
        track->filetype_marker = 0x4d503320; /* "MP3 " */
        track->visible = 1;

        itdb_track_add(db, track, -1);
        itdb_playlist_add_track(master, track, -1);
        error = NULL;
        if (!itdb_cp_track_to_ipod(track, field[0], &error)) {
            fprintf(stderr, "line %u: ", line_number);
            print_error("copy failed", error);
            itdb_track_remove(track);
            failed++;
            g_strfreev(field);
            continue;
        }
        printf("ADD\t%s\t%s\t%s\n", field[2], field[1],
               track->ipod_path ? track->ipod_path : "");
        added++;
        g_strfreev(field);
    }

    int result = 0;
    gboolean write_succeeded = TRUE;
    if (added > 0 || removed > 0) {
        error = NULL;
        if (!itdb_write(db, &error)) {
            print_error("database write failed", error);
            write_succeeded = FALSE;
            result = 1;
        }
    }
    if (write_succeeded) {
        for (guint i = 0; i < duplicate_files->len; i++) {
            const char *filename = g_ptr_array_index(duplicate_files, i);
            if (unlink(filename) != 0 && errno != ENOENT) {
                fprintf(stderr, "warning: could not remove duplicate media file: %s\n", filename);
            }
        }
    }
    printf("SUMMARY\tadded=%u\tskipped=%u\tremoved=%u\tfailed=%u\n",
           added, skipped, removed, failed);
    if (failed > 0 && result == 0) result = 3;

    g_strfreev(lines);
    g_free(contents);
    g_ptr_array_free(duplicate_files, TRUE);
    itdb_free(db);
    return result;
}
