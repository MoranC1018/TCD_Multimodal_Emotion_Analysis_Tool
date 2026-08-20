package ie.tcd.multimodal.rocksteady;

import com.treocht.notification.gui.articletablemodel.ArticleSeriesTableModel;
import com.treocht.rocksteady.textanalysis.Dictionary;
import com.treocht.rocksteady.textanalysis.DictionaryCategory;
import com.treocht.rocksteady.textanalysis.SeriesOfArticleBuckets;
import com.treocht.rocksteady.textanalysis.article.ArticlesAnalyser;
import com.treocht.rocksteady.textanalysis.articleselector.SingleArticleBucketSelector;
import com.treocht.rocksteady.textanalysis.filter.ValueType;
import com.treocht.rocksteady.textanalysis.io.DictionaryIO;
import com.treocht.rocksteady.textanalysis.io.DirectoryBackedArticleList;
import com.treocht.rocksteady.textanalysis.simple.SimpleArticlesAnalyser;
import com.treocht.util.csv.CSVOutputter;
import org.apache.log4j.Level;
import org.apache.log4j.Logger;

import java.io.BufferedWriter;
import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.OutputStreamWriter;
import java.io.Writer;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.List;

/** Minimal headless entry point around RockSteady's existing analysis engine. */
public final class RockSteadyCli {
    private RockSteadyCli() {
    }

    public static void main(String[] args) throws Exception {
        Logger.getRootLogger().setLevel(Level.WARN);
        Arguments parsed = Arguments.parse(args);
        Dictionary dictionary = loadDictionaries(parsed);
        List<DictionaryCategory> validatedCategories = selectCategories(
                dictionary.getAllCategories(), parsed.categories);
        if (parsed.validateOnly) {
            Collections.sort(validatedCategories, new Comparator<DictionaryCategory>() {
                public int compare(DictionaryCategory left, DictionaryCategory right) {
                    return left.getName().compareToIgnoreCase(right.getName());
                }
            });
            List<String> names = new ArrayList<String>();
            for (DictionaryCategory category : validatedCategories) {
                names.add(category.getName());
            }
            System.out.println(
                    "ROCKSTEADY_ADAPTER_VALID categories=" + names.size()
                            + " names=" + join(names, "|"));
            return;
        }
        DirectoryBackedArticleList articles =
                new DirectoryBackedArticleList(parsed.inputDirectory, false);
        if (articles.size() == 0) {
            throw new IllegalArgumentException(
                    "No RockSteady-readable files found in " + parsed.inputDirectory);
        }

        ArticlesAnalyser analyser = SimpleArticlesAnalyser.getArticlesAnalyser();
        SeriesOfArticleBuckets series = analyser.analyse(
                articles,
                dictionary,
                SingleArticleBucketSelector.getInstance(),
                parsed.threads,
                null,
                null);

        List<DictionaryCategory> categories = selectCategories(
                series.getAllDictionaryCategories(), parsed.categories);
        Collections.sort(categories, new Comparator<DictionaryCategory>() {
            public int compare(DictionaryCategory left, DictionaryCategory right) {
                return left.getName().compareToIgnoreCase(right.getName());
            }
        });
        ArticleSeriesTableModel model = new ArticleSeriesTableModel(
                series, ValueType.valueOf(parsed.valueType.toUpperCase()), categories, null, null);
        writeModel(model, parsed.outputFile);
        System.out.println(
                "ROCKSTEADY_ADAPTER_OK rows=" + model.getRowCount()
                        + " columns=" + model.getColumnCount()
                        + " output=" + parsed.outputFile.getAbsolutePath());
    }

    private static String join(List<String> values, String separator) {
        StringBuilder result = new StringBuilder();
        for (int index = 0; index < values.size(); index++) {
            if (index > 0) {
                result.append(separator);
            }
            result.append(values.get(index));
        }
        return result.toString();
    }

    private static Dictionary loadDictionaries(Arguments parsed) throws Exception {
        Dictionary combined = null;
        for (String resource : parsed.dictionaryResources) {
            Dictionary next = loadEmbeddedDictionary(resource);
            combined = combined == null ? next : combine(combined, next, parsed.combination);
        }
        for (File file : parsed.dictionaryFiles) {
            if (!file.isFile()) {
                throw new IllegalArgumentException("Dictionary file not found: " + file);
            }
            Dictionary next = DictionaryIO.getConcreteInstanceByFileExtension(file.getName())
                    .getAffectDictionaryFromFile(file.getAbsolutePath());
            combined = combined == null ? next : combine(combined, next, parsed.combination);
        }
        if (combined == null) {
            throw new IllegalArgumentException("At least one dictionary is required");
        }
        return combined;
    }

    private static Dictionary combine(Dictionary left, Dictionary right, String combination)
            throws Exception {
        if ("merge".equals(combination)) {
            return left.or(right);
        }
        if ("override".equals(combination)) {
            return left.overrideWith(right);
        }
        throw new IllegalArgumentException("Unsupported dictionary combination: " + combination);
    }

    private static Dictionary loadEmbeddedDictionary(String resourceName) throws Exception {
        ClassLoader loader = RockSteadyCli.class.getClassLoader();
        InputStream stream = loader.getResourceAsStream(resourceName);
        if (stream == null) {
            throw new IllegalArgumentException(
                    "Dictionary resource not found in RockSteady JAR: " + resourceName);
        }
        try {
            return DictionaryIO.getXMLInstance().getAffectDictionaryFromStream(stream);
        } finally {
            stream.close();
        }
    }

    private static List<DictionaryCategory> selectCategories(
            java.util.Set<DictionaryCategory> available, List<String> requested) {
        List<DictionaryCategory> selected = new ArrayList<DictionaryCategory>();
        if (requested.isEmpty()) {
            selected.addAll(available);
        } else {
            for (String name : requested) {
                DictionaryCategory match = null;
                for (DictionaryCategory category : available) {
                    if (category.getName().equalsIgnoreCase(name)) {
                        if (match != null) {
                            throw new IllegalArgumentException(
                                    "Ambiguous category name (case-insensitive): " + name);
                        }
                        match = category;
                    }
                }
                if (match == null) {
                    throw new IllegalArgumentException("Dictionary category not found: " + name);
                }
                selected.add(match);
            }
        }
        return selected;
    }

    private static void writeModel(ArticleSeriesTableModel model, File output) throws Exception {
        File parent = output.getParentFile();
        if (parent != null && !parent.isDirectory() && !parent.mkdirs()) {
            throw new IllegalStateException("Could not create output directory: " + parent);
        }
        List<List<?>> table = new ArrayList<List<?>>();
        List<Object> headings = new ArrayList<Object>();
        for (int column = 0; column < model.getColumnCount(); column++) {
            headings.add(model.getColumnName(column));
        }
        table.add(headings);
        for (int row = 0; row < model.getRowCount(); row++) {
            List<Object> values = new ArrayList<Object>();
            for (int column = 0; column < model.getColumnCount(); column++) {
                values.add(model.getValueAt(row, column));
            }
            table.add(values);
        }
        Collections.sort(table.subList(1, table.size()), new Comparator<List<?>>() {
            public int compare(List<?> left, List<?> right) {
                return String.valueOf(left.get(0)).compareToIgnoreCase(String.valueOf(right.get(0)));
            }
        });
        Writer writer = new BufferedWriter(new OutputStreamWriter(
                new FileOutputStream(output), StandardCharsets.UTF_8));
        try {
            CSVOutputter.getWindowsOutputter().appendTable(table, writer);
            writer.flush();
        } finally {
            writer.close();
        }
    }

    private static final class Arguments {
        private File inputDirectory;
        private File outputFile;
        private final List<String> dictionaryResources = new ArrayList<String>();
        private final List<File> dictionaryFiles = new ArrayList<File>();
        private final List<String> categories = new ArrayList<String>();
        private String combination = "merge";
        private String analyser = "simple";
        private String valueType = "total";
        private int threads = 1;
        private boolean validateOnly = false;

        private static Arguments parse(String[] args) {
            Arguments parsed = new Arguments();
            for (int i = 0; i < args.length; i++) {
                String option = args[i];
                if ("--input".equals(option)) {
                    parsed.inputDirectory = new File(requireValue(args, ++i, option));
                } else if ("--output".equals(option)) {
                    parsed.outputFile = new File(requireValue(args, ++i, option));
                } else if ("--dictionary-resource".equals(option)) {
                    parsed.dictionaryResources.add(requireValue(args, ++i, option));
                } else if ("--dictionary-file".equals(option)) {
                    parsed.dictionaryFiles.add(new File(requireValue(args, ++i, option)));
                } else if ("--dictionary-combination".equals(option)) {
                    parsed.combination = requireValue(args, ++i, option).toLowerCase();
                } else if ("--analyser".equals(option)) {
                    parsed.analyser = requireValue(args, ++i, option).toLowerCase();
                } else if ("--value-type".equals(option)) {
                    parsed.valueType = requireValue(args, ++i, option).toLowerCase();
                } else if ("--category".equals(option)) {
                    parsed.categories.add(requireValue(args, ++i, option));
                } else if ("--threads".equals(option)) {
                    parsed.threads = Integer.parseInt(requireValue(args, ++i, option));
                } else if ("--validate-only".equals(option)) {
                    parsed.validateOnly = true;
                } else {
                    throw new IllegalArgumentException("Unknown argument: " + option);
                }
            }
            if ((!parsed.validateOnly
                    && (parsed.inputDirectory == null || parsed.outputFile == null))
                    || (parsed.dictionaryResources.isEmpty() && parsed.dictionaryFiles.isEmpty())) {
                throw new IllegalArgumentException(
                        "Required: at least one dictionary, plus --input DIR --output CSV "
                                + "unless --validate-only is used");
            }
            if (parsed.threads < 1) {
                throw new IllegalArgumentException("--threads must be at least 1");
            }
            if (!"merge".equals(parsed.combination) && !"override".equals(parsed.combination)) {
                throw new IllegalArgumentException(
                        "--dictionary-combination must be merge or override");
            }
            if (!"simple".equals(parsed.analyser)) {
                throw new IllegalArgumentException(
                        "This RockSteady build only has a working simple analyser");
            }
            if (!"total".equals(parsed.valueType) && !"percentage".equals(parsed.valueType)
                    && !"z_score".equals(parsed.valueType)) {
                throw new IllegalArgumentException(
                        "--value-type must be total, percentage, or z_score");
            }
            return parsed;
        }

        private static String requireValue(String[] args, int index, String option) {
            if (index >= args.length) {
                throw new IllegalArgumentException("Missing value for " + option);
            }
            return args[index];
        }
    }
}
