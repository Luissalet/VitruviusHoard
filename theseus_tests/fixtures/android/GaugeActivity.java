package com.theseus.fixture;

import android.app.Activity;
import android.os.Bundle;
import android.widget.Button;

public class GaugeActivity extends Activity {
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        Button button = new Button(this);
        button.setText("Compute 128");
        button.setOnClickListener(view -> button.setText("Value " + new Gauge().normalize(0)));
        setContentView(button);
    }
}
